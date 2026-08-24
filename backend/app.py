"""
FastAPI backend for the Tourplay team-icon tool.

Serves:
  - GET  /                -> the single-page frontend
  - POST /api/process     -> upload an image, get back a Tourplay-ready PNG
  - GET  /api/health       -> basic health check (also warms up the model)
"""
from __future__ import annotations

import io
import logging
import os

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from PIL import Image

from processing import NoSubjectDetected, get_session, process_image

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tourplay-icon-tool")

APP_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(APP_DIR, "..", "frontend")

# Accept fairly generous uploads (phone photos etc.) but keep a sane cap so a
# huge file can't tie up the Pi for minutes.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB
ALLOWED_CONTENT_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/bmp",
    "image/gif",
}

app = FastAPI(title="Tourplay Team Icon Tool")


@app.middleware("http")
async def no_cache_for_frontend(request: Request, call_next):
    """Force browsers and any caching proxy in front of this app (e.g. a
    Cloudflare Tunnel, which by default caches static file types like .css
    and .js at its edge for hours) to always revalidate the frontend files
    instead of serving a stale copy after a deploy. `no-cache` still allows
    an efficient 304 response via the ETag/Last-Modified StaticFiles already
    sets -- it just stops anything from skipping the check entirely."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.on_event("startup")
def _warm_up_model() -> None:
    # Loading the ONNX model takes a couple of seconds; do it once at startup
    # rather than on the first user request.
    logger.info("Loading background-removal model...")
    get_session()
    logger.info("Model ready.")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/process")
async def process(file: UploadFile = File(...)):
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{file.content_type}'. "
            f"Please upload a PNG, JPEG, WEBP, BMP, or GIF image.",
        )

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({len(raw) / 1_000_000:.1f} MB). "
            f"Max upload size is {MAX_UPLOAD_BYTES / 1_000_000:.0f} MB.",
        )

    try:
        Image.open(io.BytesIO(raw)).verify()
    except Exception:
        raise HTTPException(status_code=400, detail="File is not a valid image.")

    try:
        result = process_image(raw)
    except NoSubjectDetected as exc:
        # Auto-processing couldn't find anything to keep. The frontend
        # detects this specific header and falls back to a manual crop tool
        # rather than just showing a dead-end error.
        raise HTTPException(
            status_code=422,
            detail=str(exc),
            headers={"X-Error-Code": "no_subject_detected"},
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Processing failed")
        raise HTTPException(status_code=500, detail=f"Processing failed: {exc}")

    headers = {
        "X-Output-Width": str(result.width),
        "X-Output-Height": str(result.height),
        "X-Output-Bytes": str(result.file_size_bytes),
        "Access-Control-Expose-Headers": "X-Output-Width, X-Output-Height, X-Output-Bytes",
    }
    return Response(content=result.png_bytes, media_type="image/png", headers=headers)


# Serve the frontend last so it doesn't shadow the /api routes above.
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
