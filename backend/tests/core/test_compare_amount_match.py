"""Tests for the amount *matching* ladder.

`compare.amount` decides whether the money is right. This decides whether the
screenshot is talking about this transaction at all, which is a different
question with a different answer on the same inputs — the point of the split.
"""

from __future__ import annotations

import pytest

from proofpay.core.compare.amount_match import (
    AMOUNT_MATCH,
    amount_match_ctx,
    compare_amount_match,
)
from proofpay.core.compare.levels import always
from proofpay.core.money import MINOR_EXPONENT, Money

RS_2000 = Money(200_000)


def level(claim: Money | None, ledger: Money | None, *, tolerance_minor: int = 0) -> str:
    return compare_amount_match(claim, ledger, tolerance_minor=tolerance_minor).level_code


def test_equal_amounts_match_exactly():
    assert level(RS_2000, Money(200_000)) == "AMT_EXACT"


def test_a_difference_of_one_paisa_is_not_exact():
    assert level(Money(200_001), RS_2000) == "AMT_ELSE"


def test_a_tolerance_admits_a_small_difference_under_its_own_level():
    assert level(Money(200_050), RS_2000, tolerance_minor=100) == "AMT_TOLERANCE"


def test_the_default_tolerance_is_exact_equality():
    """MVP position: integer paisa, no slack. AMT_TOLERANCE exists for a future
    provider-specific tolerance, and must not quietly widen AMT_EXACT."""
    assert level(Money(200_001), RS_2000, tolerance_minor=0) == "AMT_ELSE"


@pytest.mark.parametrize(
    ("claim_minor", "ledger_minor"),
    [
        (500_000, 50_000),      # a digit typed in: Rs 500 claimed as Rs 5,000
        (50_000, 500_000),      # a digit dropped by OCR
        (5_000_000, 50_000),    # two digits
    ],
)
def test_a_factor_of_ten_keeps_the_candidate_in_play(claim_minor, ledger_minor):
    """The attacker edits the amount on a receipt they really do hold, so the
    amount must not veto the transaction — but it is nowhere near agreement."""
    outcome = compare_amount_match(
        Money(claim_minor), Money(ledger_minor), tolerance_minor=0
    )
    assert outcome.level_code == "AMT_SCALED"
    assert outcome.score < 0.5


def test_an_unrelated_amount_does_not_match():
    assert level(Money(777_000), RS_2000) == "AMT_ELSE"


def test_an_unreadable_amount_is_missing_not_wrong():
    outcome = compare_amount_match(None, RS_2000, tolerance_minor=0)
    assert outcome.level_code == "AMT_MISSING"
    assert outcome.is_missing


def test_two_absent_amounts_do_not_match_each_other():
    outcome = compare_amount_match(None, None, tolerance_minor=0)
    assert outcome.level_code == "AMT_MISSING"


def test_a_second_currency_cannot_exist_without_being_registered():
    """Why the mismatch branch below needs a monkeypatch to reach at all.

    `MINOR_EXPONENT` is the whole currency table and it holds one entry, so
    today every `Money` in the system is PKR by construction. That makes the
    branch defensive rather than dead: the table is documented as something to
    extend deliberately, and the day a second currency is added the branch is
    live on the first mixed comparison.
    """
    assert set(MINOR_EXPONENT) == {"PKR"}
    with pytest.raises(ValueError, match="unknown currency"):
        Money(200_000, "USD")


def test_a_currency_mismatch_degrades_instead_of_raising(monkeypatch):
    """`Money.__sub__` raises across currencies; a misread symbol is a
    comparison outcome, not a programming error.

    This used to pass the *same* currency on both sides and assert
    `same_currency is True`, which exercised no mismatch at all. Registering a
    second currency for the duration of the test is what makes the branch
    reachable, and it is the same one-line change a real second currency would
    be. The assertion that matters is the last one: equal integers in different
    currencies are not equal money, and must never reach `AMT_EXACT`.
    """
    monkeypatch.setitem(MINOR_EXPONENT, "USD", 2)
    usd = Money(200_000, "USD")

    ctx = amount_match_ctx(RS_2000, usd, tolerance_minor=0)
    assert ctx["both_present"] is True
    assert ctx["same_currency"] is False
    assert ctx["diff_minor"] is None      # never a subtraction across currencies
    assert ctx["equal"] is False
    assert ctx["within_tolerance"] is False
    assert ctx["scaled"] is False

    outcome = compare_amount_match(RS_2000, usd, tolerance_minor=0)
    assert outcome.level_code == "AMT_ELSE"
    assert outcome.is_missing is False, "a mismatch is not an unreadable field"

    lenient = compare_amount_match(RS_2000, usd, tolerance_minor=1_000_000)
    assert lenient.level_code == "AMT_ELSE", "no tolerance spans two currencies"


def test_the_ladder_is_total_and_ordered():
    scores = [lvl.score for lvl in AMOUNT_MATCH.levels]
    assert scores == sorted(scores, reverse=True)
    assert AMOUNT_MATCH.levels[-1].predicate is always
    assert len(set(AMOUNT_MATCH.codes)) == len(AMOUNT_MATCH.codes)


def test_the_detail_records_the_tolerance_that_was_applied():
    detail = compare_amount_match(RS_2000, RS_2000, tolerance_minor=250).detail
    assert detail["t_tolerance_minor"] == 250
    assert detail["claim_minor"] == 200_000
    assert detail["ledger_minor"] == 200_000
