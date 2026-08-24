"""
Image processing pipeline: remove background, then shape the result to meet
Tourplay.net's published team-emblem requirements:

  - PNG (or GIF) format with a transparent background
  - Minimum dimensions: 320x320 pixels
  - Maximum file size: 2 MB
  - "Fill at least 3/4 of the space reserved for display" (Tourplay support docs)
  - Cropped to the visible pixels, no stray transparent margins baked in
    beyond what's needed to keep the subject inset from the edge

This module is deliberately independent of the web framework so it can be
unit-tested / re-used from a CLI if needed.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image
from rembg import remove, new_session

# Minimum required by Tourplay. We default the *output* canvas well above
# this so the emblem still looks crisp on retina/high-DPI screens, per their
# "must have the pixel resolution necessary to display clearly on any screen
# or device (including retina displays)" requirement.
MIN_DIMENSION = 320
MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024  # 2 MB

# How much of the square canvas the cropped subject should occupy.
# Tourplay asks for "at least 3/4" fill, so we default to 0.85 to comfortably
# clear that bar while leaving a small margin so nothing is clipped by the
# platform's own display mask (many sites render emblems in a circle/rounded
# square crop).
DEFAULT_FILL_RATIO = 0.85

# Model is loaded once per process and reused across requests -- reloading
# it per-request is the single biggest performance killer on a Raspberry Pi.
_SESSION = None


def get_session():
    global _SESSION
    if _SESSION is None:
        _SESSION = new_session("u2net")
    return _SESSION


@dataclass
class ProcessResult:
    png_bytes: bytes
    width: int
    height: int
    file_size_bytes: int


def remove_background(image_bytes: bytes) -> Image.Image:
    """Run the ML background remover and return an RGBA PIL Image."""
    session = get_session()
    out_bytes = remove(image_bytes, session=session)
    img = Image.open(io.BytesIO(out_bytes)).convert("RGBA")
    return img


def _crop_to_content(img: Image.Image) -> Image.Image:
    """Crop away fully-transparent margins, keeping only the visible subject."""
    alpha = img.split()[-1]
    bbox = alpha.getbbox()
    if bbox is None:
        # Fully transparent image (shouldn't normally happen) -- return as-is.
        return img
    return img.crop(bbox)


def _compose_square(
    subject: Image.Image, canvas_size: int, fill_ratio: float
) -> Image.Image:
    """Paste the (already cropped) subject, centered, onto a transparent
    square canvas of canvas_size x canvas_size, scaled so its longest edge
    occupies fill_ratio of the canvas."""
    sw, sh = subject.size
    target_edge = int(canvas_size * fill_ratio)
    scale = target_edge / max(sw, sh)
    new_w = max(1, round(sw * scale))
    new_h = max(1, round(sh * scale))
    resized = subject.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    offset = ((canvas_size - new_w) // 2, (canvas_size - new_h) // 2)
    canvas.paste(resized, offset, resized)
    return canvas


def _encode_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _shrink_until_under_limit(
    img: Image.Image, max_bytes: int, min_dimension: int
) -> bytes:
    """If the encoded PNG exceeds max_bytes, progressively downscale the
    canvas (never below min_dimension) until it fits, or we can't shrink
    further."""
    data = _encode_png(img)
    size = img.size[0]
    while len(data) > max_bytes and size > min_dimension:
        size = max(min_dimension, int(size * 0.85))
        resized = img.resize((size, size), Image.LANCZOS)
        data = _encode_png(resized)
        img = resized
    return data


def process_image(
    image_bytes: bytes,
    canvas_size: int = 800,
    fill_ratio: float = DEFAULT_FILL_RATIO,
) -> ProcessResult:
    """Full pipeline: remove background -> crop to content -> compose onto a
    transparent square canvas -> encode as PNG, guaranteed to satisfy
    Tourplay's minimum-dimension / max-file-size / transparency rules."""
    canvas_size = max(canvas_size, MIN_DIMENSION)

    bg_removed = remove_background(image_bytes)
    cropped = _crop_to_content(bg_removed)
    composed = _compose_square(cropped, canvas_size, fill_ratio)
    png_bytes = _shrink_until_under_limit(composed, MAX_FILE_SIZE_BYTES, MIN_DIMENSION)

    final_img = Image.open(io.BytesIO(png_bytes))
    return ProcessResult(
        png_bytes=png_bytes,
        width=final_img.width,
        height=final_img.height,
        file_size_bytes=len(png_bytes),
    )
