"""Timezone-aware instants, and an honest record of what we assumed.

Asia/Karachi is UTC+05:00 with no DST and no scheduled transitions, which makes
this domain unusually kind — but that is not a licence to store naive datetimes
and add five hours. Everything crossing into the core is converted to UTC and
must already be aware; `require_aware` is the tollbooth.

Nothing here reads the wall clock. The current instant is a parameter, always.

The screenshot's clock is not a timestamp. It is a rendering of a wall clock on
an untrusted device, with several independent unknowns: how precise the reading
was, whether a zone was stated, and whether a date was shown at all.
`ClaimedInstant` models those unknowns as data rather than pretending we hold an
instant, because they change the tolerance a comparison is entitled to use.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

#: `UTC` is imported rather than defined, and re-exported deliberately:
#: every module in `core` should reach for one canonical UTC.
__all__ = [
    "GRANULARITY_DAY",
    "GRANULARITY_MINUTE",
    "GRANULARITY_SECOND",
    "PKT",
    "PKT_NAME",
    "UTC",
    "ClaimedInstant",
    "hour_offset_artifact",
    "require_aware",
    "seconds_between",
]

PKT = ZoneInfo("Asia/Karachi")

# Granularity is "how wide is the interval this reading actually pins down",
# in seconds. These three cover every receipt layout seen so far.
GRANULARITY_SECOND = 1
GRANULARITY_MINUTE = 60
GRANULARITY_DAY = 86_400

PKT_NAME = "Asia/Karachi"


def require_aware(dt: datetime) -> datetime:
    """Convert to UTC, refusing naive datetimes at the boundary.

    A naive datetime inside the engine is the single most productive bug factory
    in this domain: it silently means "local, probably, maybe" and every later
    conversion compounds the error. Reject it here, loudly.
    """
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError("naive datetime crossed the core boundary")
    return dt.astimezone(UTC)


def seconds_between(a: datetime, b: datetime) -> float:
    """Signed seconds `a - b`. Both sides are normalised to UTC first."""
    return (require_aware(a) - require_aware(b)).total_seconds()


def hour_offset_artifact(delta_s: float, tol_s: float) -> int | None:
    """Return the whole-hour multiple this delta sits on, or None.

    A delta within `tol_s` of an exact non-zero multiple of 3600s is almost
    never clock skew — it is a timezone/offset artefact or a doctored
    screenshot. It must surface as an observation, never be quietly absorbed
    into tolerance. `tol_s` comes from policy; this module holds no thresholds.
    """
    if tol_s < 0:
        raise ValueError("tol_s must be >= 0")
    hours = round(delta_s / 3600.0)
    return hours if hours != 0 and abs(delta_s - hours * 3600) <= tol_s else None


@dataclass(frozen=True, slots=True, kw_only=True)
class ClaimedInstant:
    """A time read off an untrusted receipt, plus what we had to assume.

    `resolved_utc` is the best-effort instant. The other fields say how much to
    trust it:

    * `granularity_s` — the resolution actually visible on the receipt.
    * `assumed_tz` — the zone we applied; meaningful only when `tz_stated` is
      False, in which case it is an assumption, not a fact.
    * `tz_stated` — did the receipt actually name a zone or offset?
    * `date_inferred` — did we borrow the upload date because the receipt showed
      only a time? An inferred date misdates anything uploaded after midnight,
      so tolerance widens to the day and `VERIFIED` must never rest on it alone.
    """

    resolved_utc: datetime
    granularity_s: int = GRANULARITY_SECOND
    assumed_tz: str = PKT_NAME
    tz_stated: bool = False
    date_inferred: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "resolved_utc", require_aware(self.resolved_utc))
        if self.granularity_s <= 0:
            raise ValueError("granularity_s must be positive")

    @classmethod
    def from_local(
        cls,
        local: datetime,
        *,
        tz: ZoneInfo = PKT,
        granularity_s: int = GRANULARITY_SECOND,
        tz_stated: bool = False,
        date_inferred: bool = False,
    ) -> ClaimedInstant:
        """Attach `tz` to a naive receipt reading and resolve it to UTC.

        This is the one place a naive datetime is legitimate — the OCR layer
        genuinely has "04:12 PM" and nothing else — and it is legitimate only
        because the caller states the zone being assumed.
        """
        aware = local if local.tzinfo is not None else local.replace(tzinfo=tz)
        return cls(
            resolved_utc=aware.astimezone(UTC),
            granularity_s=granularity_s,
            assumed_tz=str(getattr(tz, "key", tz)) if local.tzinfo is None else str(aware.tzinfo),
            tz_stated=tz_stated,
            date_inferred=date_inferred,
        )

    @property
    def is_precise(self) -> bool:
        """True when the receipt pinned the instant to a minute or better."""
        return not self.date_inferred and self.granularity_s <= GRANULARITY_MINUTE

    @property
    def uncertainty_s(self) -> float:
        """Half the granularity window: the reading's own error bar, in seconds."""
        return self.granularity_s / 2.0

    def window(self) -> tuple[datetime, datetime]:
        """The interval this reading actually pins down, as [start, end)."""
        span = timedelta(seconds=self.granularity_s)
        return self.resolved_utc, self.resolved_utc + span
