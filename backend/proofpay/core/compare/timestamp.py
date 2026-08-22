"""The `timestamp` comparison: a decay curve wrapped in discrete levels.

Two ideas, kept apart on purpose:

1. **Continuous similarity** (``detail["sim"]``) comes from a Gaussian decay
   over the distance between the ledger transaction's instant and the interval
   the receipt actually pins down. It exists for the evidence drawer and for
   threshold tuning, never as the headline - "0.7314" means nothing to a
   merchant.
2. **A discrete level** is what the decision consumes. "Within a few minutes"
   is a sentence a merchant can act on, and a level ladder has a finite number
   of outcomes, so it can be tested exhaustively.

Three domain facts shape the ladder:

* **Tolerance is not one number.** A receipt whose date we had to infer from
  the upload, or one that showed only a date and no clock, deserves a far wider
  free window than one showing seconds; policy carries both parameter sets.
  Separately, the distance being decayed is measured to the *interval the
  reading actually pins down* (``ClaimedInstant.window()``), not to a point, so
  a date-only receipt is not silently treated as if it named midnight.
* **A whole-hour difference is not skew.** It is a timezone/offset artefact or
  a doctored screenshot, and it must surface as its own level rather than being
  absorbed by tolerance or silently scored as a plain mismatch.
* **An imprecise reading may never look precise.** ``TS_TIGHT`` and
  ``TS_CLOSE`` are gated on ``ClaimedInstant.is_precise``; a date-only receipt
  tops out at ``TS_DATE_ONLY`` no matter how close the instants happen to be.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Final, Protocol

from proofpay.core.compare.decay import gauss
from proofpay.core.compare.levels import (
    Agreement,
    Comparison,
    FieldOutcome,
    Level,
    else_level,
)
from proofpay.core.reasons import ObservationCode
from proofpay.core.timex import (
    ClaimedInstant,
    hour_offset_artifact,
    require_aware,
    seconds_between,
)

__all__ = [
    "MAX_HOUR_ARTIFACT",
    "TIMESTAMP",
    "TimestampParams",
    "TimestampPolicy",
    "compare_timestamp",
    "timestamp_ctx",
    "timestamp_observations",
    "window_gap_s",
]

# The cut-points that carve this decay curve into rungs used to live here as
# module constants. They do not any more: changing one changes a verdict, and a
# number that changes a verdict has to be inside the policy fingerprint or a
# stored decision is not reconstructable from its stamps. They arrive on
# `TimestampParams`, are published into `FieldOutcome.detail` as `t_sim_*`, and
# the level predicates read them from there - so the evidence drawer shows the
# thresholds the level actually fired against.

#: A whole-hour difference is only a *timezone* story while it stays inside the
#: range of real UTC offsets (14h either way). 24h is a multiple of 3600 too,
#: but a transaction a day away is a different transaction, not a mis-set clock.
MAX_HOUR_ARTIFACT: Final[int] = 14


class TimestampPolicy(Protocol):
    """The slice of `DecisionPolicy` this comparison needs.

    Declared structurally so `core.compare` never imports `core.decide`; the
    real policy object satisfies it by having these attribute names.
    """

    ts_offset_s: float
    ts_scale_s: float
    ts_offset_s_date_inferred: float
    ts_scale_s_date_inferred: float
    hour_artifact_tol_s: float
    ts_sim_tight_t: float
    ts_sim_close_t: float
    ts_sim_loose_t: float


@dataclass(frozen=True, slots=True, kw_only=True)
class TimestampParams:
    """Decay parameters for one comparison, sourced from policy.

    No defaults on purpose: a tolerance that can be forgotten is a tolerance
    nobody versioned. Callers pass `TimestampParams.from_policy(policy)`.
    """

    offset_s: float
    scale_s: float
    offset_s_date_inferred: float
    scale_s_date_inferred: float
    hour_artifact_tol_s: float
    #: Where this curve is cut into rungs. Sourced from policy like everything
    #: else here, never from a module constant.
    sim_tight: float
    sim_close: float
    sim_loose: float

    def __post_init__(self) -> None:
        if self.offset_s < 0 or self.offset_s_date_inferred < 0:
            raise ValueError("offsets must be >= 0")
        if self.scale_s <= 0 or self.scale_s_date_inferred <= 0:
            raise ValueError("scales must be > 0")
        if self.hour_artifact_tol_s < 0:
            raise ValueError("hour_artifact_tol_s must be >= 0")
        for name in ("sim_tight", "sim_close", "sim_loose"):
            value = getattr(self, name)
            if not (0.0 <= value <= 1.0):
                raise ValueError(f"{name} must be within 0.0..1.0, got {value}")
        if not (self.sim_tight >= self.sim_close >= self.sim_loose):
            raise ValueError("similarity cut-points must satisfy tight >= close >= loose")

    @classmethod
    def from_policy(cls, policy: TimestampPolicy) -> TimestampParams:
        return cls(
            offset_s=policy.ts_offset_s,
            scale_s=policy.ts_scale_s,
            offset_s_date_inferred=policy.ts_offset_s_date_inferred,
            scale_s_date_inferred=policy.ts_scale_s_date_inferred,
            hour_artifact_tol_s=policy.hour_artifact_tol_s,
            sim_tight=policy.ts_sim_tight_t,
            sim_close=policy.ts_sim_close_t,
            sim_loose=policy.ts_sim_loose_t,
        )

    def for_claim(self, claim: ClaimedInstant) -> tuple[float, float]:
        """The (offset, scale) pair this reading is entitled to.

        `is_precise` is the switch rather than `date_inferred` alone: a receipt
        showing only a date and a receipt whose date we borrowed from the upload
        are different failures, but both mean the same thing here - the clock
        time is not something we know - so both get the wide pair. How much the
        reading itself failed to pin down is handled separately, by measuring
        distance to its window instead of to a point.
        """
        if claim.is_precise:
            return self.offset_s, self.scale_s
        return self.offset_s_date_inferred, self.scale_s_date_inferred


def window_gap_s(claim: ClaimedInstant, txn_at: datetime) -> float:
    """Unsigned seconds from the transaction to the reading's window.

    A reading is an interval, not an instant: "04:12 PM" pins down a minute and
    a bare date pins down a day. Measuring to the nearest edge of that interval
    (zero while inside it) keeps the decay honest in both directions - a
    date-only receipt would otherwise be judged as if it had claimed midnight,
    making a genuine 6 p.m. transaction look eighteen hours wrong.
    """
    txn = require_aware(txn_at)
    start, end = claim.window()
    if start <= txn < end:
        return 0.0
    return min(abs(seconds_between(txn, start)), abs(seconds_between(txn, end)))


def timestamp_ctx(
    claim: ClaimedInstant | None,
    txn_at: datetime | None,
    params: TimestampParams,
) -> Mapping[str, Any]:
    """Pre-compute every metric the timestamp levels read.

    Returned read-only and used verbatim as `FieldOutcome.detail`, so the
    evidence drawer shows exactly the numbers the level fired on - including
    which tolerance pair was in force, which is the first thing anyone
    disputing a decision asks about.
    """
    if claim is None or txn_at is None:
        return MappingProxyType(
            {
                "delta_s": None,
                "abs_delta_s": None,
                "gap_s": None,
                "sim": 0.0,
                "offset_s": None,
                "scale_s": None,
                "hour_offset": None,
                "precise": False,
                "date_inferred": claim.date_inferred if claim is not None else False,
                "granularity_s": claim.granularity_s if claim is not None else None,
                "tz_stated": claim.tz_stated if claim is not None else False,
                "t_sim_tight": params.sim_tight,
                "t_sim_close": params.sim_close,
                "t_sim_loose": params.sim_loose,
            }
        )

    offset_s, scale_s = params.for_claim(claim)
    delta_s = seconds_between(claim.resolved_utc, txn_at)
    gap_s = window_gap_s(claim, txn_at)
    # A whole-hour artefact is a statement about a *clock reading*. An
    # imprecise reading has no clock to be an hour out by, and midnight-anchored
    # day windows would make every on-the-hour transaction look like one.
    hours = (
        hour_offset_artifact(delta_s, params.hour_artifact_tol_s)
        if claim.is_precise
        else None
    )
    if hours is not None and abs(hours) > MAX_HOUR_ARTIFACT:
        hours = None
    return MappingProxyType(
        {
            "delta_s": delta_s,
            "abs_delta_s": abs(delta_s),
            "gap_s": gap_s,
            "sim": gauss(gap_s, offset_s, scale_s),
            "offset_s": offset_s,
            "scale_s": scale_s,
            "hour_offset": hours,
            "precise": claim.is_precise,
            "date_inferred": claim.date_inferred,
            "granularity_s": claim.granularity_s,
            "tz_stated": claim.tz_stated,
            "t_sim_tight": params.sim_tight,
            "t_sim_close": params.sim_close,
            "t_sim_loose": params.sim_loose,
        }
    )


#: The field weight is deliberately absent here (it defaults to 1.0): how much
#: a timestamp counts towards the aggregate steers decisions, so it lives in
#: `DecisionPolicy.w_timestamp` and reaches the fingerprint. This object owns
#: the ladder, not the field's importance.
TIMESTAMP: Final[Comparison] = Comparison(
    field="timestamp",
    levels=(
        Level(
            "TS_TIGHT",
            "Same time as the transaction",
            1.00,
            lambda a, b, c: c["precise"] and c["sim"] >= c["t_sim_tight"],
            Agreement.AGREE,
        ),
        Level(
            "TS_CLOSE",
            "Within a few minutes of the transaction",
            0.85,
            lambda a, b, c: c["precise"] and c["sim"] >= c["t_sim_close"],
            Agreement.AGREE,
        ),
        # An imprecise reading can be consistent, but never precise. Scored
        # below TS_CLOSE because "some time that day" is genuinely less
        # evidence, and placed after it so that a date-only receipt can never
        # be reported as "same time".
        Level(
            "TS_DATE_ONLY",
            "Consistent with the transaction, but the receipt fixed only the date",
            0.60,
            lambda a, b, c: c["sim"] >= c["t_sim_close"],
            # Consistent with the transaction, but only to the day: it does not
            # disagree, it simply pins nothing down.
            Agreement.WEAK,
        ),
        Level(
            "TS_LOOSE",
            "Roughly the same time",
            0.50,
            lambda a, b, c: c["sim"] >= c["t_sim_loose"],
            Agreement.WEAK,
        ),
        Level(
            "TS_HOUR_ART",
            "Differs by a whole number of hours",
            0.25,
            lambda a, b, c: c["hour_offset"] is not None,
            # The classic AM/PM or time-zone artefact — worth a second look,
            # not an accusation, and certainly not a fact that should on its
            # own send an otherwise perfect match to a human.
            Agreement.WEAK,
        ),
        Level(
            "TS_MISSING",
            "No usable time on the receipt",
            0.00,
            lambda a, b, c: c["delta_s"] is None,
            Agreement.MISSING,
        ),
        else_level(
            "TS_ELSE",
            "Times do not correspond",
            agreement=Agreement.CONTRADICT,
        ),
    ),
)


def compare_timestamp(
    claim: ClaimedInstant | None,
    txn_at: datetime | None,
    params: TimestampParams,
) -> FieldOutcome:
    """Build the metrics and evaluate the ladder - the callable most callers want."""
    return TIMESTAMP.evaluate(claim, txn_at, timestamp_ctx(claim, txn_at, params))


def timestamp_observations(outcome: FieldOutcome) -> tuple[str, ...]:
    """Neutral notes implied by a timestamp outcome, in a stable order.

    Observations are not reasons: they record what we had to assume, and the
    rule table decides whether that matters. They live here because this module
    owns the metric keys they are derived from.
    """
    detail = outcome.detail
    notes: list[str] = []
    if detail.get("date_inferred"):
        notes.append(str(ObservationCode.TIME_DATE_INFERRED))
    if detail.get("delta_s") is not None and not detail.get("tz_stated"):
        notes.append(str(ObservationCode.TIME_TZ_ASSUMED))
    if detail.get("hour_offset") is not None:
        notes.append(str(ObservationCode.TIME_WHOLE_HOUR_OFFSET))
    return tuple(notes)
