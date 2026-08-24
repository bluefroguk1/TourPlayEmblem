# Tourplay Team Icon Tool
#
# Built and run directly on the Raspberry Pi (arm64) with `docker compose
# build` -- no cross-compilation needed. Requires a 64-bit OS (Raspberry Pi
# OS Bookworm 64-bit or similar); onnxruntime does not ship 32-bit ARM
# wheels.

FROM python:3.11-slim-bookworm

# Runtime libs needed by opencv-python-headless (a rembg dependency) and by
# onnxruntime's threaded execution.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend ./backend
COPY frontend ./frontend

# Where rembg caches the downloaded ONNX model. Point this at a volume (see
# docker-compose.yml) so the ~176MB model survives container rebuilds and
# doesn't need to be re-downloaded every time.
ENV U2NET_HOME=/app/model-cache
RUN mkdir -p /app/model-cache

EXPOSE 8000

WORKDIR /app/backend

# Single worker: the model is loaded once per worker process, and a Pi's
# RAM is better spent on one warm model than several duplicated copies.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
