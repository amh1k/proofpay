"""Image preprocessing: deterministic, versioned, and the entire cost driver.

Normalises an uploaded receipt image into a `PreparedImage` that every extractor
and tamper analyser sees identically. The key operation is `smart_resize` which
snaps dimensions to multiples of the Qwen-VL patch factor (32), so the token
estimate is exact and the model's server-side resize is a no-op.

Nothing here reads the network or any API key.
"""

from __future__ import annotations

import hashlib
import io
import math
from dataclasses import dataclass

from PIL import Image, ImageOps

__all__ = ["PREPROC_VERSION", "PreparedImage", "prepare", "smart_resize"]

PREPROC_VERSION = "preproc/v1"
FACTOR = 32  # Qwen3-VL family (incl. qwen-vl-ocr); use 28 for Qwen2.5-VL
MIN_PIXELS = FACTOR * FACTOR * 4
MAX_PIXELS = FACTOR * FACTOR * 4096
MAX_RATIO = 200


def _round_by(n: float, f: int) -> int:
    return round(n / f) * f


def _ceil_by(n: float, f: int) -> int:
    return math.ceil(n / f) * f


def _floor_by(n: float, f: int) -> int:
    return math.floor(n / f) * f


def smart_resize(
    height: int,
    width: int,
    factor: int = FACTOR,
    min_pixels: int = MIN_PIXELS,
    max_pixels: int = MAX_PIXELS,
) -> tuple[int, int]:
    """Port of qwen_vl_utils.vision_process.smart_resize (verbatim algorithm)."""
    if max_pixels < min_pixels:
        raise ValueError("max_pixels must be >= min_pixels")
    if max(height, width) / max(min(height, width), 1) > MAX_RATIO:
        raise ValueError(f"aspect ratio must be < {MAX_RATIO}")

    h_bar = max(factor, _round_by(height, factor))
    w_bar = max(factor, _round_by(width, factor))

    if h_bar * w_bar > max_pixels:
        beta = math.sqrt((height * width) / max_pixels)
        h_bar = _floor_by(height / beta, factor)
        w_bar = _floor_by(width / beta, factor)
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h_bar = _ceil_by(height * beta, factor)
        w_bar = _ceil_by(width * beta, factor)

    return h_bar, w_bar


@dataclass(frozen=True)
class PreparedImage:
    """A normalised receipt image ready for extraction."""

    png_bytes: bytes
    width: int
    height: int
    est_image_tokens: int
    source_sha256: str  # hash of the ORIGINAL upload
    prepared_sha256: str  # hash of what we actually sent
    preproc_version: str


def prepare(raw: bytes) -> PreparedImage:
    """Normalise raw upload bytes into a PreparedImage.

    Steps (in order, each deliberate):
    1. EXIF transpose — phone photos carry orientation metadata
    2. Convert to RGB — kill alpha, palettes, CMYK
    3. smart_resize — snap to Qwen-VL patch-factor multiples
    4. Re-encode to lossless PNG — never add JPEG compression generations
    5. Hash both source and prepared for provenance
    """
    src_hash = hashlib.sha256(raw).hexdigest()
    with Image.open(io.BytesIO(raw)) as im:
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
        h, w = smart_resize(im.height, im.width)
        if (w, h) != im.size:
            # Never upscale past native: it adds tokens, not information
            if w * h > im.width * im.height:
                w = _floor_by(im.width, FACTOR) or FACTOR
                h = _floor_by(im.height, FACTOR) or FACTOR
            im = im.resize((w, h), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="PNG", optimize=False, compress_level=6)
    out = buf.getvalue()
    return PreparedImage(
        png_bytes=out,
        width=w,
        height=h,
        est_image_tokens=(w * h) // (FACTOR * FACTOR),
        source_sha256=src_hash,
        prepared_sha256=hashlib.sha256(out).hexdigest(),
        preproc_version=PREPROC_VERSION,
    )
