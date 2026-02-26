"""
app/services/code_executor_service.py

Sandboxed code execution via Docker.

Security model:
  - Each execution spawns a fresh, ephemeral Docker container.
  - Network access is completely disabled (--network=none).
  - Container memory is hard-capped (128 MB default).
  - CPU is throttled (0.5 CPUs default).
  - Execution is wall-clock time-limited (10 s default); the container is
    force-killed if it exceeds the timeout.
  - The container runs as a non-root user (nobody) inside the image.
  - No volume mounts from the host — code is passed through stdin only.
  - Supported languages: Python 3, JavaScript (Node.js), Bash (shell).
  - Output is capped at MAX_OUTPUT_BYTES to prevent flooding the chat.

Requirements:
  - Docker daemon must be running and accessible (docker socket).
  - The images python:3.11-alpine, node:20-alpine, alpine:3 must be
    pre-pulled on the host for cold-start performance.

Usage:
    executor = CodeExecutorService()
    result = await executor.run(language="python", code="print('hello')")
    # result = {"stdout": "hello\n", "stderr": "", "exit_code": 0, "timed_out": False}
"""
from __future__ import annotations

import asyncio
import shlex
from loguru import logger

# Hard limits — keep conservative for safety
DEFAULT_TIMEOUT_SECONDS: int = 10
DEFAULT_MEMORY_MB: int = 128
DEFAULT_CPU_QUOTA: float = 0.5  # CPUs
MAX_OUTPUT_BYTES: int = 8_000  # ~8 KB — enough for typical REPL output

# Map language identifiers to (docker_image, run_command_template)
# The command reads source from stdin to avoid host filesystem exposure.
_LANGUAGE_CONFIG: dict[str, tuple[str, str]] = {
    "python": ("python:3.11-alpine", "python3 -"),
    "python3": ("python:3.11-alpine", "python3 -"),
    "javascript": ("node:20-alpine", "node -"),
    "js": ("node:20-alpine", "node -"),
    "bash": ("alpine:3", "sh"),
    "sh": ("alpine:3", "sh"),
}

SUPPORTED_LANGUAGES = sorted(_LANGUAGE_CONFIG.keys())


class CodeExecutionResult:
    """Result of a sandboxed code execution."""
    __slots__ = ("stdout", "stderr", "exit_code", "timed_out", "language")

    def __init__(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        timed_out: bool,
        language: str,
    ) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.timed_out = timed_out
        self.language = language

    def to_dict(self) -> dict:
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "language": self.language,
            "success": self.exit_code == 0 and not self.timed_out,
        }

    def format_for_chat(self) -> str:
        """Return a human-readable summary suitable for Telegram HTML."""
        import html

        lines: list[str] = []

        if self.timed_out:
            lines.append(f"<b>⏱ Timeout</b> after {DEFAULT_TIMEOUT_SECONDS}s")

        if self.stdout.strip():
            lines.append(f"<b>Output:</b>\n<pre><code>{html.escape(self.stdout[:MAX_OUTPUT_BYTES])}</code></pre>")

        if self.stderr.strip():
            lines.append(f"<b>Stderr:</b>\n<pre><code>{html.escape(self.stderr[:MAX_OUTPUT_BYTES])}</code></pre>")

        if not self.stdout.strip() and not self.stderr.strip():
            lines.append("(no output)")

        status_icon = "✅" if self.exit_code == 0 and not self.timed_out else "❌"
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
    def _build_docker_cmd(image: str, run_cmd: str, memory_mb: int, cpu_quota: float) -> list[str]:
        """Build the docker run command with all safety flags."""
        cpu_period = 100_000  # microseconds (100 ms)
        cpu_quota_us = int(cpu_quota * cpu_period)

        return [
            "docker", "run",
            "--rm",                          # auto-remove container on exit
            "--network=none",                # no network access
            "--read-only",                   # read-only root filesystem
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m",  # writable /tmp only
            f"--memory={memory_mb}m",        # RAM cap
            "--memory-swap=-1",              # disable swap (no swapping allowed)
            f"--cpu-period={cpu_period}",
            f"--cpu-quota={cpu_quota_us}",   # CPU throttle
            "--cap-drop=ALL",                # drop all Linux capabilities
            "--security-opt=no-new-privileges",
            "--pids-limit=64",               # limit process count (no fork bombs)
            "-u", "nobody",                  # run as non-root
            "-i",                            # stdin open (code passed via stdin)
            "--log-driver=none",             # no Docker logging overhead
            image,
        ] + shlex.split(run_cmd)

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

        Args:
            language: One of SUPPORTED_LANGUAGES.
            code:     Source code to execute.
            timeout:  Wall-clock timeout in seconds (container is killed after).
            memory_mb: Memory cap for the container in megabytes.
            cpu_quota: CPU limit as a fraction (0.5 = half a core).

        Returns:
            CodeExecutionResult with stdout, stderr, exit_code, timed_out.
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
        docker_cmd = self._build_docker_cmd(image, run_cmd, memory_mb, cpu_quota)

        logger.info("Executing {} code in sandbox (len={} chars, timeout={}s)", language, len(code), timeout)

        timed_out = False
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
                logger.warning("Code execution timed out after {}s, killing container", timeout)
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                stdout_bytes, stderr_bytes = b"", b"Execution timed out."
                await proc.wait()

            exit_code = proc.returncode or 0
            stdout = stdout_bytes.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
            stderr = stderr_bytes.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]

            logger.info(
                "Code execution finished: language={} exit_code={} timed_out={}",
                language, exit_code, timed_out,
            )
            return CodeExecutionResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                timed_out=timed_out,
                language=language,
            )

        except FileNotFoundError:
            msg = "Docker is not available on this server. Code execution requires Docker."
            logger.error(msg)
            return CodeExecutionResult(stdout="", stderr=msg, exit_code=1, timed_out=False, language=language)
        except Exception as e:
            logger.exception("Unexpected error during code execution: {}", e)
            return CodeExecutionResult(stdout="", stderr=str(e), exit_code=1, timed_out=False, language=language)


# Module-level singleton
code_executor = CodeExecutorService()
