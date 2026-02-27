"""
app/services/code_executor_service.py

Sandboxed code execution via Docker with file output support.

Security model:
  - Each execution spawns a fresh, ephemeral Docker container.
  - Network access is completely disabled (--network=none).
  - Root filesystem is read-only (--read-only).
  - /tmp is an in-memory tmpfs (rw, noexec, 32 MB).
  - /output is a per-execution host directory mounted read-write.
    It is the ONLY path code can write files to that persist after container exit.
    The host directory is deleted immediately after files are collected.
  - Container memory is hard-capped.
  - CPU is throttled.
  - Execution is wall-clock time-limited; container is force-killed on timeout.
  - Container runs as non-root user (nobody).
  - No volume mounts from sensitive host paths.
  - Supported languages: python (rich sandbox image), javascript (node), bash.

Python sandbox image (motivi-sandbox:latest) pre-installed libraries:
  matplotlib, numpy, pandas, scipy, seaborn   — data viz & analysis
  python-docx                                  — Word (.docx) files
  openpyxl                                     — Excel (.xlsx) files
  python-pptx                                  — PowerPoint (.pptx) files
  Pillow                                        — image processing

File output:
  Code saves files to /output/ inside the container.
  After execution, any files present in /output/ (up to MAX_OUTPUT_FILES,
  each up to MAX_FILE_BYTES) are collected and returned in CodeExecutionResult.output_files.
  The caller is responsible for sending them to Telegram.

Build the sandbox image once:
  docker build -f docker/sandbox.Dockerfile -t motivi-sandbox:latest .

Also pre-pull basic images:
  docker pull node:20-alpine
  docker pull alpine:3
"""
from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from loguru import logger

# ── Hard limits ──────────────────────────────────────────────────────────────
DEFAULT_TIMEOUT_SECONDS: int = 30         # generous for matplotlib/docx generation
DEFAULT_MEMORY_MB: int = 256             # matplotlib needs more than 128 MB
DEFAULT_CPU_QUOTA: float = 0.5           # CPUs

MAX_OUTPUT_BYTES: int = 8_000            # stdout/stderr cap (~8 KB)
MAX_OUTPUT_FILES: int = 10               # max files collected from /output/
MAX_FILE_BYTES: int = 10 * 1024 * 1024  # 10 MB per file
MAX_TOTAL_BYTES: int = 25 * 1024 * 1024 # 25 MB total across all output files

# Allowed output file extensions (prevents arbitrary binary exfiltration)
ALLOWED_EXTENSIONS: frozenset[str] = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp",  # images
    ".pdf",                                      # PDF
    ".docx",                                     # Word
    ".xlsx",                                     # Excel
    ".pptx",                                     # PowerPoint
    ".csv", ".tsv",                              # tabular text
    ".txt", ".md", ".json", ".xml", ".html",     # text formats
})

# ── Language → (docker image, run command) ───────────────────────────────────
# motivi-sandbox:latest is a custom image with matplotlib/docx/xlsx/pptx.
# Build it with: docker build -f docker/sandbox.Dockerfile -t motivi-sandbox:latest .
_LANGUAGE_CONFIG: dict[str, tuple[str, str]] = {
    "python":     ("motivi-sandbox:latest", "python3 -"),
    "python3":    ("motivi-sandbox:latest", "python3 -"),
    "javascript": ("node:20-alpine",        "node -"),
    "js":         ("node:20-alpine",        "node -"),
    "bash":       ("alpine:3",              "sh"),
    "sh":         ("alpine:3",              "sh"),
}

# Languages whose image has /output pre-created (supports file output)
_FILE_OUTPUT_LANGUAGES: frozenset[str] = frozenset({"python", "python3"})

SUPPORTED_LANGUAGES: list[str] = sorted(_LANGUAGE_CONFIG.keys())

# Host base dir for per-execution output subdirs.
# Must be the same absolute path on the HOST and inside the app container
# (see docker-compose.yml volume: /tmp/motivi_exec:/tmp/motivi_exec).
_EXEC_BASE_DIR = "/tmp/motivi_exec"


@dataclass
class CodeExecutionResult:
    """Result of a sandboxed code execution."""
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    language: str
    # List of (filename, file_bytes) collected from /output/ inside the sandbox.
    # Populated only for Python executions that write to /output/.
    output_files: list[tuple[str, bytes]] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def to_dict(self) -> dict:
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "language": self.language,
            "success": self.success,
            "output_file_names": [name for name, _ in self.output_files],
        }

    def format_for_chat(self) -> str:
        """Return a human-readable summary suitable for Telegram HTML."""
        import html as _html
        lines: list[str] = []

        if self.timed_out:
            lines.append(f"<b>⏱ Timeout</b> after {DEFAULT_TIMEOUT_SECONDS}s")

        if self.stdout.strip():
            lines.append(
                f"<b>Output:</b>\n<pre><code>{_html.escape(self.stdout[:MAX_OUTPUT_BYTES])}</code></pre>"
            )
        if self.stderr.strip():
            lines.append(
                f"<b>Stderr:</b>\n<pre><code>{_html.escape(self.stderr[:MAX_OUTPUT_BYTES])}</code></pre>"
            )
        if not self.stdout.strip() and not self.stderr.strip() and not self.output_files:
            lines.append("(no output)")

        if self.output_files:
            names = ", ".join(name for name, _ in self.output_files)
            lines.append(f"<b>📎 Files saved:</b> {_html.escape(names)}")

        status_icon = "✅" if self.success else "❌"
        lines.append(f"{status_icon} Exit code: {self.exit_code}")
        return "\n".join(lines)


class CodeExecutorService:
    """
    Executes user-supplied code in an isolated Docker sandbox.
    Stateless — safe to use as a module-level singleton.
    """

    @staticmethod
    async def is_docker_available() -> bool:
        """Check if Docker CLI is accessible."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "info",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            return proc.returncode == 0
        except FileNotFoundError:
            return False

    @staticmethod
    def _collect_output_files(output_dir: str) -> list[tuple[str, bytes]]:
        """
        Scan output_dir and collect files that are within size/extension limits.
        Returns list of (filename, bytes) sorted by name.
        """
        collected: list[tuple[str, bytes]] = []
        total_bytes = 0

        try:
            entries = sorted(os.listdir(output_dir))
        except OSError:
            return []

        for fname in entries:
            if len(collected) >= MAX_OUTPUT_FILES:
                logger.warning("Output file limit ({}) reached, skipping remaining files", MAX_OUTPUT_FILES)
                break

            fpath = os.path.join(output_dir, fname)
            if not os.path.isfile(fpath):
                continue

            ext = Path(fname).suffix.lower()
            if ext not in ALLOWED_EXTENSIONS:
                logger.warning("Skipping output file with disallowed extension: {}", fname)
                continue

            fsize = os.path.getsize(fpath)
            if fsize > MAX_FILE_BYTES:
                logger.warning("Skipping output file too large ({} bytes): {}", fsize, fname)
                continue
            if total_bytes + fsize > MAX_TOTAL_BYTES:
                logger.warning("Total output size limit reached, skipping: {}", fname)
                break

            try:
                with open(fpath, "rb") as f:
                    data = f.read()
                collected.append((fname, data))
                total_bytes += fsize
                logger.debug("Collected output file: {} ({} bytes)", fname, fsize)
            except OSError as e:
                logger.warning("Could not read output file {}: {}", fname, e)

        return collected

    @staticmethod
    def _build_docker_cmd(
        image: str,
        run_cmd: str,
        memory_mb: int,
        cpu_quota: float,
        container_name: str,
        output_host_dir: str | None = None,
    ) -> list[str]:
        """Build the docker run command with all safety flags."""
        cpu_period = 100_000
        cpu_quota_us = int(cpu_quota * cpu_period)

        cmd = [
            "docker", "run",
            "--rm",
            f"--name={container_name}",  # named so we can force-kill on timeout
            "--network=none",
            "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m",
            f"--memory={memory_mb}m",
            f"--memory-swap={memory_mb}m",  # same value = no swap allowed
            f"--cpu-period={cpu_period}",
            f"--cpu-quota={cpu_quota_us}",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=64",
            "-u", "nobody",
            "-i",
            "--log-driver=none",
            # Env vars so matplotlib / libraries use /tmp for configs, not ~
            "-e", "MPLCONFIGDIR=/tmp",
            "-e", "MPLBACKEND=Agg",
            "-e", "HOME=/tmp",
            "-e", "XDG_CONFIG_HOME=/tmp",
        ]

        # Mount the per-execution output directory if provided
        if output_host_dir:
            cmd += ["-v", f"{output_host_dir}:/output:rw"]

        cmd.append(image)
        cmd += shlex.split(run_cmd)
        return cmd

    async def run(
        self,
        language: str,
        code: str,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        memory_mb: int = DEFAULT_MEMORY_MB,
        cpu_quota: float = DEFAULT_CPU_QUOTA,
    ) -> CodeExecutionResult:
        """
        Execute the given code string in a sandboxed Docker container.

        For Python, creates a temporary /output directory on the host that is
        mounted into the container. Any files saved to /output/ inside the
        container are collected and returned in CodeExecutionResult.output_files.

        Args:
            language:  One of SUPPORTED_LANGUAGES.
            code:      Source code to execute.
            timeout:   Wall-clock timeout in seconds.
            memory_mb: Memory cap in MB.
            cpu_quota: CPU limit as a fraction of one core.

        Returns:
            CodeExecutionResult with stdout, stderr, exit_code, timed_out, output_files.
        """
        lang_key = language.lower().strip()
        if lang_key not in _LANGUAGE_CONFIG:
            return CodeExecutionResult(
                stdout="",
                stderr=f"Unsupported language '{language}'. Supported: {', '.join(SUPPORTED_LANGUAGES)}",
                exit_code=1,
                timed_out=False,
                language=language,
            )

        image, run_cmd = _LANGUAGE_CONFIG[lang_key]
        supports_file_output = lang_key in _FILE_OUTPUT_LANGUAGES

        # Unique container name allows explicit force-kill on timeout
        container_name = f"motivi-exec-{uuid.uuid4().hex[:12]}"

        # Create isolated per-execution output directory on host
        output_host_dir: str | None = None
        if supports_file_output:
            try:
                os.makedirs(_EXEC_BASE_DIR, exist_ok=True)
                output_host_dir = os.path.join(_EXEC_BASE_DIR, uuid.uuid4().hex)
                os.makedirs(output_host_dir, mode=0o777, exist_ok=False)
            except OSError as e:
                logger.warning("Could not create output dir: {}; file output disabled", e)
                output_host_dir = None

        docker_cmd = self._build_docker_cmd(
            image, run_cmd, memory_mb, cpu_quota, container_name, output_host_dir
        )

        logger.info(
            "Executing {} code in sandbox (container={}, len={} chars, timeout={}s, file_output={})",
            language, container_name, len(code), timeout, output_host_dir is not None,
        )

        timed_out = False
        output_files: list[tuple[str, bytes]] = []

        try:
            proc = await asyncio.create_subprocess_exec(
                *docker_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(input=code.encode("utf-8", errors="replace")),
                    timeout=float(timeout),
                )
            except asyncio.TimeoutError:
                timed_out = True
                logger.warning(
                    "Code execution timed out after {}s, force-killing container {}",
                    timeout, container_name,
                )
                # Kill the docker CLI process
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                # Force-kill the container via Docker daemon (belt-and-suspenders)
                try:
                    kill_proc = await asyncio.create_subprocess_exec(
                        "docker", "kill", container_name,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await asyncio.wait_for(kill_proc.wait(), timeout=5.0)
                except Exception:
                    pass  # container may have already exited
                stdout_bytes, stderr_bytes = b"", b"Execution timed out."
                await proc.wait()

            exit_code = proc.returncode or 0
            stdout = stdout_bytes.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
            stderr = stderr_bytes.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]

            # Collect output files (only for Python sandbox)
            if output_host_dir:
                output_files = self._collect_output_files(output_host_dir)

            logger.info(
                "Code execution finished: language={} exit_code={} timed_out={} files={}",
                language, exit_code, timed_out, len(output_files),
            )
            return CodeExecutionResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                timed_out=timed_out,
                language=language,
                output_files=output_files,
            )

        except FileNotFoundError:
            msg = "Docker is not available on this server. Code execution requires Docker."
            logger.error(msg)
            return CodeExecutionResult(
                stdout="", stderr=msg, exit_code=1, timed_out=False, language=language
            )
        except Exception as e:
            logger.exception("Unexpected error during code execution: {}", e)
            return CodeExecutionResult(
                stdout="", stderr=str(e), exit_code=1, timed_out=False, language=language
            )
        finally:
            # Always clean up the host output directory
            if output_host_dir:
                try:
                    shutil.rmtree(output_host_dir, ignore_errors=True)
                except Exception as e:
                    logger.warning("Failed to clean up output dir {}: {}", output_host_dir, e)


# Module-level singleton
code_executor = CodeExecutorService()
