# Motivi sandbox image for user code execution.
# Built once on the host; used by code_executor_service.py for every Python execution.
#
# Security model:
#   - Runs as non-root (nobody) user inside the container.
#   - No network access at runtime (--network=none passed by executor).
#   - Root FS is read-only at runtime (--read-only).
#   - /tmp is a small tmpfs (rw, noexec).
#   - /output is volume-mounted from the host (rw) — the ONLY place code can write files.
#   - All other security flags (--cap-drop=ALL, --pids-limit, --memory) are set by executor.
#
# Pre-installed libraries (no internet access at execution time):
#   matplotlib, numpy, pandas, scipy, seaborn       — data viz & analysis
#   python-docx                                      — Word (.docx) documents
#   openpyxl                                         — Excel (.xlsx) spreadsheets
#   python-pptx                                      — PowerPoint (.pptx) presentations
#   Pillow                                            — image manipulation
#
# Build:
#   docker build -f docker/sandbox.Dockerfile -t motivi-sandbox:latest .
#
# Pre-pull on host (run once before starting the app):
#   docker build -f docker/sandbox.Dockerfile -t motivi-sandbox:latest .

FROM python:3.11-slim

# Minimal system deps for matplotlib (font/png rendering)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libfreetype6 \
        libpng16-16 \
        libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*

# Pin versions for reproducibility
RUN pip install --no-cache-dir \
        matplotlib==3.8.4 \
        numpy==1.26.4 \
        pandas==2.2.2 \
        scipy==1.13.1 \
        seaborn==0.13.2 \
        python-docx==1.1.2 \
        openpyxl==3.1.5 \
        python-pptx==1.0.2 \
        Pillow==10.4.0

# /output is the only directory code should write files to.
# Permissions are 777 so the 'nobody' user can write even without explicit chown.
RUN mkdir /output && chmod 777 /output

# Drop to non-root for all subsequent operations and at runtime
USER nobody

# No CMD / ENTRYPOINT — the executor passes the command explicitly.
