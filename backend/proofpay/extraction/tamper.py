"""CPU-only image tamper observations.

WHY THIS MODULE EXISTS:
    Screenshots are untrusted input. Fraudsters edit amounts, TIDs, or dates
    using Photoshop, Canva, or phone photo editors. This module computes
    cheap, CPU-only observations about image provenance and structure.

CRITICAL INVARIANTS:
    1. These are OBSERVATIONS, NEVER VERDICTS. None of them may set SUSPICIOUS
       alone; at most they contribute an observation to the decision engine.
    2. No `severity: "critical"`. No `is_tampered: bool`. No aggregate score.
    3. Hashing operates on `PreparedImage` / raw bytes for absolute determinism.
"""

from __future__ import annotations

import io

import imagehash
from PIL import Image

from proofpay.extraction.preprocess import PreparedImage
from proofpay.extraction.schema import TamperObservation

__all__ = ["TAMPER_VERSION", "analyze_tamper"]

TAMPER_VERSION = "tamper/v1"

# Common mobile screen aspect ratios (width:height when portrait)
# Standard ratios: 9:16 (~0.5625), 9:19.5 (~0.4615), 9:20 (~0.4500), 9:21 (~0.4286)
_KNOWN_PORTRAIT_RATIOS = (0.5625, 0.4615, 0.4500, 0.4286, 0.5000)
_RATIO_TOLERANCE = 0.03

# Known image editor software signatures in EXIF/PNG metadata
_EDITOR_SIGNATURES = (
    "photoshop",
    "gimp",
    "canva",
    "snapseed",
    "lightroom",
    "pixlr",
    "picsart",
    "paint.net",
    "affinity",
)


def analyze_tamper(raw_bytes: bytes, prepared: PreparedImage) -> list[TamperObservation]:
    """Compute CPU-only tamper observations on raw and prepared image data.

    Returns a list of TamperObservation records. Returns an empty list if no
    anomalies are detected. Never raises exceptions on malformed metadata.
    """
    observations: list[TamperObservation] = []

    # 1. Near-duplicate perceptual hashes (stored on prepared image)
    try:
        phash_val, dhash_val = _compute_perceptual_hashes(prepared.png_bytes)
        observations.append(
            TamperObservation(
                code="IMAGE_PHASH",
                detail=f"phash:{phash_val}; dhash:{dhash_val}",
                severity="info",
                analyzer_version=TAMPER_VERSION,
            )
        )
    except Exception:  # noqa: BLE001, S110
        pass

    # 2. Metadata / Editor signature scan
    try:
        editor_obs = _scan_metadata(raw_bytes)
        if editor_obs:
            observations.append(editor_obs)
    except Exception:  # noqa: BLE001, S110
        pass

    # 3. Dimension & aspect ratio plausibility
    try:
        dim_obs = _check_dimensions(prepared.width, prepared.height)
        if dim_obs:
            observations.append(dim_obs)
    except Exception:  # noqa: BLE001, S110
        pass

    return observations


def _compute_perceptual_hashes(png_bytes: bytes) -> tuple[str, str]:
    """Compute 256-bit (hash_size=16) pHash and dHash on PNG bytes."""
    with Image.open(io.BytesIO(png_bytes)) as img:
        p = str(imagehash.phash(img, hash_size=16))
        d = str(imagehash.dhash(img, hash_size=16))
        return p, d


def _scan_metadata(raw_bytes: bytes) -> TamperObservation | None:
    """Scan EXIF tags and PNG tEXt chunks for known image editing software."""
    found_editor: str | None = None

    with Image.open(io.BytesIO(raw_bytes)) as img:
        # Check PNG info dict (tEXt / zTXt chunks)
        if hasattr(img, "info") and isinstance(img.info, dict):
            for key, val in img.info.items():
                val_str = str(val).lower()
                for sig in _EDITOR_SIGNATURES:
                    if sig in val_str or sig in str(key).lower():
                        found_editor = f"{key}:{val}"
                        break

        # Check EXIF tags if present
        if not found_editor and hasattr(img, "getexif"):
            exif = img.getexif()
            if exif:
                for tag_id, value in exif.items():
                    val_str = str(value).lower()
                    for sig in _EDITOR_SIGNATURES:
                        if sig in val_str:
                            found_editor = f"EXIF_{tag_id}:{value}"
                            break

    if found_editor:
        return TamperObservation(
            code="IMAGE_EDITOR_SIGNATURE",
            detail=f"Image metadata contains editor signature: {found_editor}",
            severity="notice",
            analyzer_version=TAMPER_VERSION,
        )

    return None


def _check_dimensions(width: int, height: int) -> TamperObservation | None:
    """Check whether image dimensions match standard mobile portrait ratios."""
    if height <= 0 or width <= 0:
        return None

    # Ensure portrait ratio (width / height)
    ratio = width / height if width < height else height / width

    matches_known = any(
        abs(ratio - target) <= _RATIO_TOLERANCE for target in _KNOWN_PORTRAIT_RATIOS
    )

    if not matches_known:
        return TamperObservation(
            code="IMAGE_NON_STANDARD_ASPECT_RATIO",
            detail=f"Aspect ratio {ratio:.3f} ({width}x{height}) differs from standard phone screen ratios",
            severity="info",
            analyzer_version=TAMPER_VERSION,
        )

    return None
