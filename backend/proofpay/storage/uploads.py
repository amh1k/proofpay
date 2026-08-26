"""Validate and sanitise uploaded payment-proof images.

The upload boundary deliberately does not trust a browser supplied filename or
content type.  Pillow identifies the actual format, verifies that the complete
image can be decoded, strips metadata by converting to RGB, and writes a fresh
PNG.  The original bytes are retained by the caller for provenance and for the
offline demo extractor; the returned bytes are what should be stored privately.
"""

from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError
from PIL.Image import DecompressionBombError, DecompressionBombWarning

from .errors import InvalidImage, UnsupportedImage, UploadTooLarge

_FORMAT_MEDIA_TYPES = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    """Validated upload metadata and the sanitised bytes to persist."""

    original_sha256: str
    stored_sha256: str
    original_media_type: str
    stored_media_type: str
    width: int
    height: int
    original_size: int
    stored_size: int
    storage_key: str
    stored_bytes: bytes


def validate_image(content: bytes, *, max_bytes: int) -> ValidatedUpload:
    """Validate, decode, and safely re-encode an uploaded image.

    ``max_bytes`` is checked before invoking Pillow so a large request cannot
    consume decoder resources.  Decompression-bomb warnings are promoted to
    errors because this endpoint handles untrusted images.
    """

    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")
    original_size = len(content)
    if original_size == 0:
        raise InvalidImage("The uploaded file is empty")
    if original_size > max_bytes:
        raise UploadTooLarge(f"Upload exceeds the {max_bytes}-byte limit")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as probe:
                image_format = probe.format
                if image_format not in _FORMAT_MEDIA_TYPES:
                    raise UnsupportedImage(
                        "Only JPEG, PNG, and WebP images are accepted"
                    )
                probe.verify()

            # ``verify`` consumes the decoder; reopen for the actual
            # sanitisation pass.
            with Image.open(io.BytesIO(content)) as image:
                image = ImageOps.exif_transpose(image).convert("RGB")
                width, height = image.size
                output = io.BytesIO()
                image.save(output, format="PNG", optimize=False, compress_level=6)
                stored_bytes = output.getvalue()
    except (DecompressionBombError, DecompressionBombWarning) as exc:
        raise InvalidImage("The image dimensions are unsafe") from exc
    except UnsupportedImage:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InvalidImage("The uploaded file is not a readable image") from exc

    original_sha256 = hashlib.sha256(content).hexdigest()
    stored_sha256 = hashlib.sha256(stored_bytes).hexdigest()
    # The key is content-addressed and never includes a user-controlled name.
    storage_key = f"proofs/{original_sha256[:2]}/{original_sha256}.png"
    return ValidatedUpload(
        original_sha256=original_sha256,
        stored_sha256=stored_sha256,
        original_media_type=_FORMAT_MEDIA_TYPES[image_format],
        stored_media_type="image/png",
        width=width,
        height=height,
        original_size=original_size,
        stored_size=len(stored_bytes),
        storage_key=storage_key,
        stored_bytes=stored_bytes,
    )


__all__ = ["ValidatedUpload", "validate_image"]
