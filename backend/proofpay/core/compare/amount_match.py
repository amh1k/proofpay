"""Amount as a *matching* signal: does this screenshot describe this payment?

Not to be confused with `compare.amount`, which answers the two commercial /
integrity questions (was enough paid, does the proof over-claim). That module
produces a verdict about money. This one produces a rung on an evidence ladder
— one more field the retrieval scorer weighs when deciding *which* ledger row a
claim is about. Both are needed and they are genuinely different questions: a
claim inflated tenfold is strong evidence of fraud (`compare.amount`) and, at
the same time, weak-but-real evidence that this is the right transaction
(here), because an attacker edits the amount on a receipt they actually hold.

Kept in its own module rather than inside `compare.amount` so the fraud
semantics and the matching semantics can never be confused for one another at
a call site.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Final

from proofpay.core.compare.amount import is_power_of_ten_multiple
from proofpay.core.compare.levels import (
    Agreement,
    Comparison,
    FieldOutcome,
    Level,
    else_level,
)
from proofpay.core.money import Money

__all__ = [
    "AMOUNT_MATCH",
    "amount_match_ctx",
    "compare_amount_match",
]


def amount_match_ctx(
    claim: Money | None, ledger: Money | None, *, tolerance_minor: int
) -> Mapping[str, Any]:
    """Pre-compute the metrics the ladder reads.

    Arithmetic is done on `minor` directly rather than through `Money.__sub__`
    because a currency mismatch must degrade to "these do not match" rather
    than raise: an OCR misread of a currency symbol is a comparison outcome,
    not a programming error.
    """
    both = claim is not None and ledger is not None
    same_currency = both and claim.currency == ledger.currency  # type: ignore[union-attr]

    if not same_currency:
        diff: int | None = None
        equal = scaled = within = False
    else:
        assert claim is not None and ledger is not None  # narrowed by same_currency
        diff = claim.minor - ledger.minor
        equal = diff == 0
        within = -tolerance_minor <= diff <= tolerance_minor
        # A digit added or dropped at the end — the shape of both a fabricated
        # amount and an OCR truncation. Checked in both directions because the
        # ladder does not care which side lost the zero, only that the two
        # numbers are the same digits.
        scaled = is_power_of_ten_multiple(
            claim.minor, ledger.minor
        ) or is_power_of_ten_multiple(ledger.minor, claim.minor)

    return MappingProxyType(
        {
            "claim_minor": claim.minor if claim is not None else None,
            "ledger_minor": ledger.minor if ledger is not None else None,
            "both_present": both,
            "same_currency": same_currency,
            "diff_minor": diff,
            "equal": equal,
            "within_tolerance": within,
            "scaled": scaled,
            "t_tolerance_minor": tolerance_minor,
        }
    )


AMOUNT_MATCH: Final[Comparison] = Comparison(
    field="amount",
    weight=1.0,
    levels=(
        Level(
            "AMT_EXACT",
            "Amount matches the transaction exactly",
            1.00,
            lambda a, b, c: c["equal"],
            Agreement.AGREE,
        ),
        # Unreachable while `amount_tolerance_minor` is 0, which is the MVP
        # position (exact equality in integer paisa). It exists so that a
        # provider-specific tolerance, if ever justified, has a rung that says
        # so out loud instead of quietly widening AMT_EXACT.
        Level(
            "AMT_TOLERANCE",
            "Amount matches within the permitted tolerance",
            0.90,
            lambda a, b, c: c["within_tolerance"],
            Agreement.AGREE,
        ),
        # Deliberately low. It is enough to keep the candidate in play — the
        # amount comparison must not veto the transaction an attacker really
        # does hold — and nowhere near enough to carry a verification.
        #
        # And it CONTRADICTS. Rs 500 printed as Rs 5,000 is the signature edit
        # this product exists to catch, so it is not a soft near-miss between
        # AGREE and the plain mismatch: it points against the match at least as
        # hard as AMT_ELSE does. The score says how much; this says which way.
        Level(
            "AMT_SCALED",
            "Amount differs by a factor of ten",
            0.35,
            lambda a, b, c: c["scaled"],
            Agreement.CONTRADICT,
        ),
        Level(
            "AMT_MISSING",
            "No amount could be read from the receipt",
            0.00,
            lambda a, b, c: not c["both_present"],
            Agreement.MISSING,
        ),
        else_level(
            "AMT_ELSE",
            "Amount does not match the transaction",
            agreement=Agreement.CONTRADICT,
        ),
    ),
)


def compare_amount_match(
    claim: Money | None, ledger: Money | None, *, tolerance_minor: int
) -> FieldOutcome:
    """Build the metrics and evaluate the ladder."""
    return AMOUNT_MATCH.evaluate(
        claim, ledger, amount_match_ctx(claim, ledger, tolerance_minor=tolerance_minor)
    )
