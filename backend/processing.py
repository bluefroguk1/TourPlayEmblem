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

# Minimum required by Tourplay. The output canvas is chosen automatically
# per-image (see _auto_canvas_size) so it's never below this, per their
# "must have the pixel resolution necessary to display clearly on any screen
# or device (including retina displays)" requirement.
MIN_DIMENSION = 320
MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024  # 2 MB

# Upper bound on the auto-chosen canvas. Tourplay emblems are displayed as
# small icons, so there's no benefit to exporting bigger than this even from
# a very high-resolution source -- it would only inflate the file size and
# processing time for no visible gain.
MAX_CANVAS_SIZE = 1600

# How much of the square canvas the cropped subject should occupy.
# Tourplay asks for "at least 3/4" fill, so we default to 0.85 to comfortably
# clear that bar while leaving a small margin so nothing is clipped by the
# platform's own display mask (many sites render emblems in a circle/rounded
# square crop).
DEFAULT_FILL_RATIO = 0.85

# Below this many pixels on either edge, a detected "subject" is treated as
# noise rather than a real emblem -- not worth composing, better to ask the
# person to crop manually.
MIN_DETECTED_EDGE = 8

# The background-removal model rarely outputs a literally all-zero alpha
# channel, even when it completely fails to find a subject -- on a blank or
# texture-less image it instead produces low-confidence noise spread across
# the mid-range of the alpha channel (nothing near 0, nothing near 255).
# A clean, successful segmentation instead looks bimodal: the model is
# confident almost everywhere, either clearly-background (near 0) or
# clearly-foreground (near 255). So rather than trusting getbbox() (which
# treats any nonzero pixel as "content" and would see the whole image as one
# big blob of noise), we measure what fraction of pixels the model was
# actually confident about, and treat a low fraction as a failed detection.
CONFIDENT_ALPHA_LOW = 10
CONFIDENT_ALPHA_HIGH = 245
MIN_CONFIDENT_FRACTION = 0.5

# Model is loaded once per process and reused across requests -- reloading
# it per-request is the single biggest performance killer on a Raspberry Pi.
_SESSION = None


class NoSubjectDetected(Exception):
    """Raised when background removal couldn't find anything worth keeping
    (the whole image came back transparent, or only a tiny noise-sized
    fragment survived). The caller should fall back to letting the user
    manually crop the source image instead."""


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


def _confident_pixel_fraction(alpha: Image.Image) -> float:
    """Fraction of pixels the model was confident about (clearly background
    or clearly foreground), as opposed to uncertain/noisy mid-range alpha."""
    hist = alpha.histogram()
    total = sum(hist)
    if total == 0:
        return 0.0
    confident = sum(hist[: CONFIDENT_ALPHA_LOW + 1]) + sum(hist[CONFIDENT_ALPHA_HIGH:])
    return confident / total


def _crop_to_content(img: Image.Image) -> Image.Image:
    """Crop away fully-transparent margins, keeping only the visible subject.

    Raises NoSubjectDetected if background removal couldn't cleanly find a
    subject at all (low confidence across the board -- see
    _confident_pixel_fraction), or left only a noise-sized fragment. Either
    way auto-processing can't produce a sensible emblem, and the caller
    should offer a manual crop instead."""
    alpha = img.split()[-1]

    if _confident_pixel_fraction(alpha) < MIN_CONFIDENT_FRACTION:
        raise NoSubjectDetected(
            "Background removal couldn't confidently separate a subject "
            "from the background in this image."
        )

    bbox = alpha.getbbox()
    if bbox is None:
        raise NoSubjectDetected(
            "Background removal didn't find any subject in this image."
        )
    left, top, right, bottom = bbox
    if (right - left) < MIN_DETECTED_EDGE or (bottom - top) < MIN_DETECTED_EDGE:
        raise NoSubjectDetected(
            "Background removal only found a tiny, noise-sized fragment."
        )
    return img.crop(bbox)


def _auto_canvas_size(subject: Image.Image, fill_ratio: float) -> int:
    """Pick the best output canvas size for this specific image: as close to
    the subject's native resolution as possible (so we're never inventing
    detail that isn't there), clamped to [MIN_DIMENSION, MAX_CANVAS_SIZE].

    A small/low-res logo gets gently upscaled only as far as Tourplay's
    320x320 minimum requires. A large, clean source image gets a big, crisp
    export up to the cap. Either way the result always satisfies Tourplay's
    minimum-dimension requirement without unnecessary upscaling."""
    native_edge = max(subject.size)
    ideal = round(native_edge / fill_ratio)
    return max(MIN_DIMENSION, min(ideal, MAX_CANVAS_SIZE))


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
    fill_ratio: float = DEFAULT_FILL_RATIO,
) -> ProcessResult:
    """Full pipeline: remove background -> crop to content -> compose onto a
    transparent square canvas, auto-sized to the best fit for this image ->
    encode as PNG, guaranteed to satisfy Tourplay's minimum-dimension /
    max-file-size / transparency rules."""
    bg_removed = remove_background(image_bytes)
    cropped = _crop_to_content(bg_removed)
    canvas_size = _auto_canvas_size(cropped, fill_ratio)
    composed = _compose_square(cropped, canvas_size, fill_ratio)
    png_bytes = _shrink_until_under_limit(composed, MAX_FILE_SIZE_BYTES, MIN_DIMENSION)

    final_img = Image.open(io.BytesIO(png_bytes))
    return ProcessResult(
        png_bytes=png_bytes,
        width=final_img.width,
        height=final_img.height,
        file_size_bytes=len(png_bytes),
    )
