"""Deterministic parsers for amounts, timestamps, and phone numbers.

These run AFTER the VLM returns raw strings. The VLM's only job is
pixels → strings; normalisation is deterministic Python we can unit-test.

Never let the model normalise — a model returning 4500.0 as a float
has destroyed the evidence that it read '45OO' and guessed.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from proofpay.core.money import Money
from proofpay.core.timex import (
    GRANULARITY_DAY,
    GRANULARITY_MINUTE,
    GRANULARITY_SECOND,
    PKT,
    ClaimedInstant,
)

__all__ = ["normalize_msisdn", "parse_amount", "parse_timestamp"]

# ── Amount parsing ──────────────────────────────────────────────────────────

# OCR glyph confusions that are common on receipt fonts
_GLYPH_MAP = str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "S": "5"})

# Strip currency prefixes/suffixes, thousands separators, trailing /-
_CURRENCY_RE = re.compile(
    r"(?:Rs\.?\s*|PKR\s*|₨\s*)", re.IGNORECASE
)
_TRAILING_RE = re.compile(r"[/\-]+$")
_THOUSANDS_SEP_RE = re.compile(r"(?<=\d),(?=\d{3})")


def parse_amount(raw: str | None) -> Money | None:
    """Parse a raw amount string into Money (integer paisa).

    Accepts: 'Rs. 4,500/-', 'PKR 4500.00', '4,500', '4500', '₨ 1,500.50'
    Returns None on unparseable input rather than guessing.
    """
    if not raw or not raw.strip():
        return None

    text = raw.strip()
    text = _CURRENCY_RE.sub("", text).strip()
    text = _TRAILING_RE.sub("", text).strip()
    text = _THOUSANDS_SEP_RE.sub("", text)
    text = text.translate(_GLYPH_MAP)
    text = text.replace(" ", "")

    if not text:
        return None

    try:
        return Money.from_major(Decimal(text))
    except (InvalidOperation, ValueError):
        return None


# ── Timestamp parsing ───────────────────────────────────────────────────────

_DATE_FORMATS = [
    # Full formats (second precision)
    ("%d %b %Y, %I:%M %p", GRANULARITY_SECOND),
    ("%d %b %Y, %I:%M:%S %p", GRANULARITY_SECOND),
    ("%d/%m/%Y %H:%M", GRANULARITY_MINUTE),
    ("%d/%m/%Y %H:%M:%S", GRANULARITY_SECOND),
    ("%d-%m-%Y %H:%M", GRANULARITY_MINUTE),
    ("%d-%m-%Y %H:%M:%S", GRANULARITY_SECOND),
    ("%Y-%m-%d %H:%M:%S", GRANULARITY_SECOND),
    ("%d %b %Y %I:%M %p", GRANULARITY_SECOND),
    # Date-only formats (day precision)
    ("%d %b %Y", GRANULARITY_DAY),
    ("%d/%m/%Y", GRANULARITY_DAY),
    ("%d-%m-%Y", GRANULARITY_DAY),
]


def parse_timestamp(raw: str | None) -> ClaimedInstant | None:
    """Parse a raw timestamp string into a ClaimedInstant.

    Tries known Pakistani receipt date formats. The timezone is ASSUMED
    to be PKT (Asia/Karachi) unless explicitly stated — that assumption
    is recorded in the ClaimedInstant so downstream can widen tolerance.

    Returns None on unparseable input.
    """
    if not raw or not raw.strip():
        return None

    text = raw.strip()
    # Normalise common variations
    text = text.replace("  ", " ")
    text = re.sub(r"\s*(AM|PM)\s*$", r" \1", text, flags=re.IGNORECASE)

    for fmt, granularity in _DATE_FORMATS:
        try:
            dt = datetime.strptime(text, fmt)  # noqa: DTZ007 — receipts carry no tz
            return ClaimedInstant.from_local(
                dt,
                tz=PKT,
                granularity_s=granularity,
                tz_stated=False,
                date_inferred=(granularity >= GRANULARITY_DAY),
            )
        except ValueError:
            continue

    return None


# ── Phone number normalisation ──────────────────────────────────────────────

_DIGITS_ONLY = re.compile(r"\D")
_PK_MOBILE = re.compile(r"^(03\d{2})\d{7}$")


def normalize_msisdn(raw: str | None) -> str | None:
    """Normalise a Pakistani mobile number to 03XX1234567 form.

    Handles: '0301-4567890', '+92 301 456 7890', '03XX-XXXX890' (masked).
    Returns None if unparseable.
    """
    if not raw or not raw.strip():
        return None

    text = raw.strip()

    # Keep mask characters for masked numbers
    if "X" in text.upper() or "*" in text or "●" in text:
        # Return cleaned masked form
        cleaned = re.sub(r"[\s\-()]", "", text)
        return cleaned if len(cleaned) >= 10 else None

    digits = _DIGITS_ONLY.sub("", text)

    # +92 prefix
    if digits.startswith("92") and len(digits) == 12:
        digits = "0" + digits[2:]

    if _PK_MOBILE.match(digits):
        return digits

    return None
