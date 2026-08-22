"""ProofPay verification core — a pure library.

`proofpay.core` is the reproducible heart of the product. It imports only the
standard library plus `rapidfuzz` and `jellyfish`: no database, no HTTP, no
image toolkit, no filesystem, no network.

Two rules define this package, and both are enforced by `tests/test_layering.py`
rather than by good intentions:

1. No I/O. Every input arrives as an argument; every output is a value.
2. No wall clock. The current instant is always passed in as `now`, which is
   what makes a decision reconstructable months later from its stored inputs.

Public entry points are re-exported here so callers above this layer never
have to reach into submodules: `decide` turns a claim plus a ledger into a
`Decision`, and `explain` renders that `Decision` for a human.
"""

from proofpay.core.compare.levels import Comparison, FieldOutcome, Level, always, else_level
from proofpay.core.decide import ENGINE_VERSION, RULESET_VERSION, DecisionPolicy, decide
from proofpay.core.explain import Explanation, explain, render_text
from proofpay.core.models import (
    Allocation,
    Decision,
    LedgerTxn,
    Order,
    PaymentClaim,
    ScoredCandidate,
)
from proofpay.core.money import MINOR_EXPONENT, Money
from proofpay.core.reasons import (
    PARTIALLY_TRUSTED_SOURCES,
    TRUSTED_LEDGER_SOURCES,
    ObservationCode,
    ReasonCode,
    Risk,
    Source,
    Status,
)
from proofpay.core.timex import (
    GRANULARITY_DAY,
    GRANULARITY_MINUTE,
    GRANULARITY_SECOND,
    PKT,
    UTC,
    ClaimedInstant,
    hour_offset_artifact,
    require_aware,
    seconds_between,
)

__all__ = [
    "ENGINE_VERSION",
    "GRANULARITY_DAY",
    "GRANULARITY_MINUTE",
    "GRANULARITY_SECOND",
    "MINOR_EXPONENT",
    "PARTIALLY_TRUSTED_SOURCES",
    "PKT",
    "RULESET_VERSION",
    "TRUSTED_LEDGER_SOURCES",
    "UTC",
    "Allocation",
    "ClaimedInstant",
    "Comparison",
    "Decision",
    "DecisionPolicy",
    "Explanation",
    "FieldOutcome",
    "LedgerTxn",
    "Level",
    "Money",
    "ObservationCode",
    "Order",
    "PaymentClaim",
    "ReasonCode",
    "Risk",
    "ScoredCandidate",
    "Source",
    "Status",
    "always",
    "decide",
    "else_level",
    "explain",
    "hour_offset_artifact",
    "render_text",
    "require_aware",
    "seconds_between",
]
