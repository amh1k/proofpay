"""Deterministic clock for fixtures, seeds, and tests.

WHY THIS EXISTS:
    ProofPay fixtures need timestamps (receipt time, ledger time, order time).
    Using datetime.now() would make fixtures go stale overnight — case U01
    ("payment still processing, 4 minutes ago") would become "payment from
    yesterday" and flip from UNMATCHED to a different outcome.

HOW IT WORKS:
    All fixture timestamps are defined as integer minute offsets from a
    single pinned anchor: 2026-08-20 at 14:05 PKT.

    Example from manifest.json:
        "ledger_offset_min": -12   →  14:05 minus 12 = 13:53 PKT
        "claim_offset_min":  -11   →  14:05 minus 11 = 13:54 PKT

    This means:
      - Tests always use the pinned anchor → fully deterministic
      - Demo day: set PROOFPAY_DEMO_ANCHOR=today → everything shifts to today
      - The DELTA between claim and ledger is always the same (1 minute)
        regardless of when you run it

IMPORTANT:
    Almost none of the matching rules care about "now". Timestamp scoring
    compares claim vs ledger, and that delta is invariant under any anchor
    shift. Only PENDING_SETTLEMENT (U01) and feed-lag windows (U03) touch
    "now", and those are handled by injecting this clock as a dependency.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

# Pakistan Standard Time — UTC+05:00, no DST (the one easy timezone)
PKT = ZoneInfo("Asia/Karachi")

# ── The pinned anchor ─────────────────────────────────────────────
# Every timestamp in the entire fixture set is relative to this moment.
# Changing this constant changes ALL fixture times consistently.
PINNED_ANCHOR = datetime(2026, 8, 20, 14, 5, 0, tzinfo=PKT)


def anchor() -> datetime:
    """Return the current demo time anchor.

    Controlled by the PROOFPAY_DEMO_ANCHOR environment variable:

      Not set / empty → Returns the pinned constant (2026-08-20 14:05 PKT).
                         This is what tests use for full determinism.

      "today"         → Returns today's date at 14:05 PKT.
                         Use this on demo day so the data looks fresh.
                         Example: PROOFPAY_DEMO_ANCHOR=today uv run proofpay-demo seed --reset

      ISO-8601 string → Parsed literally.
                         Example: PROOFPAY_DEMO_ANCHOR=2026-08-22T10:00:00+05:00

    Returns:
        A timezone-aware datetime in PKT.
    """
    raw = os.getenv("PROOFPAY_DEMO_ANCHOR", "").strip()

    if not raw:
        # Default: the pinned constant. Tests always land here.
        return PINNED_ANCHOR

    if raw.lower() == "today":
        # Demo day: use today's date but keep the time at 14:05
        # so all the minute-offsets still make sense.
        now = datetime.now(PKT)
        return now.replace(hour=14, minute=5, second=0, microsecond=0)

    # Explicit ISO-8601: parse whatever the operator gave us
    return datetime.fromisoformat(raw)


def at(offset_minutes: int) -> datetime:
    """Return a timestamp at `offset_minutes` from the anchor.

    This is the ONLY way fixture timestamps are created.

    Args:
        offset_minutes: Minutes relative to anchor. Negative = before anchor.

    Returns:
        anchor() + timedelta(minutes=offset_minutes)

    Examples:
        at(0)    → the anchor itself (2026-08-20 14:05 PKT)
        at(-12)  → 12 minutes before anchor (13:53 PKT)
        at(5)    → 5 minutes after anchor (14:10 PKT)
        at(-240) → 4 hours before anchor (10:05 PKT)
    """
    return anchor() + timedelta(minutes=offset_minutes)


def to_utc(dt: datetime) -> datetime:
    """Convert any timezone-aware datetime to UTC.

    Used when persisting to the database — all stored timestamps are UTC.
    Display code converts back to PKT at the UI edge.

    Args:
        dt: A timezone-aware datetime (must have tzinfo set).

    Returns:
        The same instant expressed in UTC.

    Raises:
        ValueError: If dt is naive (no timezone info).
    """
    if dt.tzinfo is None:
        raise ValueError("Cannot convert naive datetime to UTC — set tzinfo first")
    return dt.astimezone(UTC)
