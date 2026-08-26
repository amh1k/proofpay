"""Amount semantics -- guide section 5.

The scenarios here are the product, not coverage padding: the Rs. 5,000-claimed
/ Rs. 500-received attack is the thing ProofPay exists to catch, and the
1-rupee difference next to it is the thing it must never accuse anyone over.
"""

import ast
import dataclasses
import pathlib

import pytest

from proofpay.core.compare.amount import (
    AmountRelation,
    ClaimIntegrity,
    compare_amounts,
    is_material_inflation,
    is_power_of_ten_multiple,
)
from proofpay.core.money import Money
from proofpay.core.reasons import ObservationCode, ReasonCode


@dataclasses.dataclass(frozen=True, slots=True)
class StubPolicy:
    """The five knobs this module reads, with the guide's section 7.3 defaults.

    Local to the test so the amount comparison stays testable before
    ``core/decide/policy.py`` exists; ``DecisionPolicy`` satisfies the same
    structural protocol.

    Kept in step with ``AmountPolicy`` by hand, which is the price of a
    structural protocol: adding a field there and forgetting it here fails
    every test in this module with an ``AttributeError`` rather than silently
    reading a default nobody chose.
    """

    amount_tolerance_minor: int = 0
    inflation_material_minor: int = 5_000  # Rs. 50
    inflation_material_pct: float = 0.01
    overpayment_material_minor: int = 20_000  # Rs. 200
    overpayment_material_pct: float = 1.0


POLICY = StubPolicy()

RS_500 = Money(50_000)
RS_5000 = Money(500_000)


# --------------------------------------------------------------------------
# A. ledger vs expected -- the commercial axis
# --------------------------------------------------------------------------


def test_exact_payment():
    ev = compare_amounts(RS_5000, RS_5000, RS_5000, POLICY)
    assert ev.relation is AmountRelation.EXACT
    assert ev.integrity is ClaimIntegrity.CONSISTENT
    assert ev.shortfall == Money(0)
    assert ev.inflation == Money(0)
    assert ev.within_tolerance is True
    assert ev.material_inflation is False
    assert ev.observations == ()
    assert ev.reason_codes == (ReasonCode.AMOUNT_EXACT, ReasonCode.CLAIM_CONSISTENT)


def test_underpayment_keeps_its_sign():
    """Rs. 5,000 asked, Rs. 4,500 arrived. Shortfall is positive."""
    ledger = Money(450_000)
    ev = compare_amounts(RS_5000, ledger, ledger, POLICY)
    assert ev.relation is AmountRelation.UNDER
    assert ev.shortfall == Money(50_000)
    assert ev.shortfall.minor > 0
    assert ev.within_tolerance is False
    assert ev.integrity is ClaimIntegrity.CONSISTENT
    assert ReasonCode.AMOUNT_UNDERPAID in ev.reason_codes
    assert ReasonCode.AMOUNT_OVERPAID not in ev.reason_codes


def test_overpayment_keeps_its_sign():
    """Rs. 5,000 asked, Rs. 5,500 arrived. Shortfall is negative, not absolute."""
    ledger = Money(550_000)
    ev = compare_amounts(RS_5000, ledger, ledger, POLICY)
    assert ev.relation is AmountRelation.OVER
    assert ev.shortfall == Money(-50_000)
    assert ev.shortfall.minor < 0
    assert ReasonCode.AMOUNT_OVERPAID in ev.reason_codes


def test_under_and_over_of_equal_size_are_different_outcomes():
    """The regression that would appear the moment somebody writes abs()."""
    under = compare_amounts(RS_5000, Money(450_000), None, POLICY)
    over = compare_amounts(RS_5000, Money(550_000), None, POLICY)
    assert under.relation is not over.relation
    assert under.shortfall != over.shortfall


@pytest.mark.parametrize(
    ("shortfall_minor", "expected_within"),
    [(0, True), (100, True), (-100, True), (101, False), (-101, False)],
)
def test_tolerance_band_is_symmetric_and_inclusive(shortfall_minor, expected_within):
    policy = StubPolicy(amount_tolerance_minor=100)
    ledger = Money(500_000)
    expected = Money(500_000 + shortfall_minor)
    ev = compare_amounts(expected, ledger, None, policy)
    assert ev.within_tolerance is expected_within


def test_tolerance_does_not_change_the_relation():
    """Within tolerance still records that it was an underpayment."""
    policy = StubPolicy(amount_tolerance_minor=100)
    ev = compare_amounts(Money(500_050), Money(500_000), None, policy)
    assert ev.relation is AmountRelation.UNDER
    assert ev.within_tolerance is True


# --------------------------------------------------------------------------
# B. claim vs ledger -- the integrity axis
# --------------------------------------------------------------------------


def test_the_five_thousand_claimed_five_hundred_received_attack():
    """The headline fraud: order Rs. 500, Rs. 500 arrived, proof says Rs. 5,000.

    The commercial axis is perfectly clean -- this is exactly why comparing
    only ledger against expected loses the signal entirely.
    """
    ev = compare_amounts(RS_500, RS_500, RS_5000, POLICY)

    assert ev.relation is AmountRelation.EXACT
    assert ev.integrity is ClaimIntegrity.INFLATED
    assert ev.inflation == Money(450_000)
    assert ev.inflation.minor > 0
    assert ev.material_inflation is True
    assert ObservationCode.CLAIM_INFLATED_ROUND in ev.observations
    assert ev.reason_codes == (ReasonCode.AMOUNT_EXACT, ReasonCode.CLAIM_INFLATED)


def test_immaterial_one_rupee_inflation_is_not_an_accusation():
    """Rs. 5,001 on the receipt, Rs. 5,000 in the bank: an OCR artefact."""
    claim = Money(500_100)
    ev = compare_amounts(RS_5000, RS_5000, claim, POLICY)

    assert ev.integrity is ClaimIntegrity.INFLATED
    assert ev.inflation == Money(100)
    assert ev.material_inflation is False, "Rs. 1 must not reach SUSPICIOUS"
    assert ev.observations == ()
    assert ReasonCode.CLAIM_INFLATED in ev.reason_codes


def test_deflation_is_low_risk_and_never_material():
    """OCR drops digits; attackers do not under-claim what they sent."""
    claim = Money(50_000)
    ev = compare_amounts(RS_5000, RS_5000, claim, POLICY)
    assert ev.integrity is ClaimIntegrity.DEFLATED
    assert ev.inflation == Money(-450_000)
    assert ev.material_inflation is False
    assert ev.observations == ()
    assert ReasonCode.CLAIM_DEFLATED in ev.reason_codes


# --------------------------------------------------------------------------
# Materiality
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("inflation_minor", "ledger_minor", "material", "why"),
    [
        (100, 500_000, False, "Rs. 1 on Rs. 5,000: under the floor"),
        (4_999, 20_000_000, False, "one paisa under the floor"),
        (5_000, 20_000, True, "clears floor and 1% of a Rs. 200 payment"),
        (5_000, 500_000, True, "clears floor and 1% of Rs. 5,000 exactly"),
        (4_999, 500_000, False, "under the floor even though it is ~1%"),
        (10_000, 10_000_000, False, "Rs. 100 on Rs. 100,000 is 0.1%: noise"),
        (100_000, 10_000_000, True, "Rs. 1,000 on Rs. 100,000 is 1%"),
        (450_000, 50_000, True, "the 10x attack"),
        (-450_000, 500_000, False, "deflation is never material"),
        (0, 500_000, False, "consistent is never material"),
    ],
)
def test_materiality_needs_both_the_floor_and_the_proportion(
    inflation_minor, ledger_minor, material, why
):
    assert is_material_inflation(inflation_minor, ledger_minor, POLICY) is material, why


def test_zero_knobs_disable_their_half_of_materiality():
    any_inflation = StubPolicy(inflation_material_minor=0, inflation_material_pct=0.0)
    assert is_material_inflation(1, 500_000, any_inflation) is True
    floor_only = StubPolicy(inflation_material_minor=5_000, inflation_material_pct=0.0)
    assert is_material_inflation(5_000, 10_000_000, floor_only) is True
    assert is_material_inflation(4_999, 10_000_000, floor_only) is False


def test_materiality_on_a_zero_ledger_falls_back_to_the_floor():
    """A Rs. 0 ledger row makes the percentage vacuous; the floor still holds."""
    assert is_material_inflation(4_999, 0, POLICY) is False
    assert is_material_inflation(5_000, 0, POLICY) is True


# --------------------------------------------------------------------------
# Power-of-ten inflation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("claim_minor", "ledger_minor", "expected"),
    [
        (500_000, 50_000, True),  # 10x -- one zero typed in
        (5_000_000, 50_000, True),  # 100x
        (50_000_000, 50_000, True),  # 1000x
        (50_000, 50_000, False),  # equal is not inflation
        (5_000, 50_000, False),  # 0.1x is deflation
        (150_000, 50_000, False),  # 3x is not a power of ten
        (450_000, 50_000, False),  # 9x -- close, still not a power of ten
        (500_001, 50_000, False),  # 10x plus a paisa: not exact
        (500_000, 0, False),  # no division by zero
    ],
)
def test_power_of_ten_multiple(claim_minor, ledger_minor, expected):
    assert is_power_of_ten_multiple(claim_minor, ledger_minor) is expected


def test_round_observation_only_fires_on_inflation():
    ev = compare_amounts(RS_500, RS_500, Money(500_000), POLICY)
    assert ev.observations == (ObservationCode.CLAIM_INFLATED_ROUND,)

    tenth = compare_amounts(RS_5000, RS_5000, Money(50_000), POLICY)
    assert tenth.integrity is ClaimIntegrity.DEFLATED
    assert tenth.observations == ()


def test_non_round_inflation_is_still_material_without_the_observation():
    """Materiality and roundness are independent signals."""
    ev = compare_amounts(RS_500, RS_500, Money(437_100), POLICY)
    assert ev.integrity is ClaimIntegrity.INFLATED
    assert ev.material_inflation is True
    assert ev.observations == ()


# --------------------------------------------------------------------------
# Missing inputs must degrade, never crash and never look like agreement
# --------------------------------------------------------------------------


def test_unreadable_claim_amount_is_unknown_not_consistent():
    ev = compare_amounts(RS_5000, RS_5000, None, POLICY)

    assert ev.integrity is ClaimIntegrity.UNKNOWN
    assert ev.inflation is None
    assert ev.claim_known is False
    assert ev.material_inflation is False
    assert ev.observations == ()
    # The commercial axis is unaffected by an unreadable screenshot.
    assert ev.relation is AmountRelation.EXACT
    assert ev.reason_codes == (ReasonCode.AMOUNT_EXACT,)
    assert ReasonCode.CLAIM_CONSISTENT not in ev.reason_codes


def test_unreadable_claim_still_reports_an_underpayment():
    ev = compare_amounts(RS_5000, Money(450_000), None, POLICY)
    assert ev.relation is AmountRelation.UNDER
    assert ev.within_tolerance is False
    assert ev.integrity is ClaimIntegrity.UNKNOWN


def test_missing_order_amount_is_unknown_not_exact():
    ev = compare_amounts(None, RS_5000, RS_5000, POLICY)

    assert ev.relation is AmountRelation.UNKNOWN
    assert ev.shortfall is None
    assert ev.expected_known is False
    # No expectation exists, so no underpayment rule may fire on it.
    assert ev.within_tolerance is True
    assert ReasonCode.MISSING_ORDER_AMOUNT in ev.reason_codes
    assert ReasonCode.AMOUNT_EXACT not in ev.reason_codes
    assert ev.integrity is ClaimIntegrity.CONSISTENT


def test_both_sides_missing():
    ev = compare_amounts(None, RS_5000, None, POLICY)
    assert ev.relation is AmountRelation.UNKNOWN
    assert ev.integrity is ClaimIntegrity.UNKNOWN
    assert ev.shortfall is None
    assert ev.inflation is None
    assert ev.reason_codes == (ReasonCode.MISSING_ORDER_AMOUNT,)


def test_missing_order_amount_still_catches_the_inflation_attack():
    ev = compare_amounts(None, RS_500, RS_5000, POLICY)
    assert ev.relation is AmountRelation.UNKNOWN
    assert ev.integrity is ClaimIntegrity.INFLATED
    assert ev.material_inflation is True


# --------------------------------------------------------------------------
# Structural guarantees
# --------------------------------------------------------------------------


def test_currency_mismatch_raises_rather_than_comparing_rupees_to_dollars():
    with pytest.raises(ValueError):
        compare_amounts(Money(500_000, "PKR"), Money(500_000, "USD"), None, POLICY)


def test_evidence_is_immutable():
    ev = compare_amounts(RS_5000, RS_5000, RS_5000, POLICY)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ev.relation = AmountRelation.UNDER  # type: ignore[misc]
    assert not hasattr(ev, "__dict__"), "slots=True: no per-instance dict"


def test_amount_module_never_calls_abs():
    """The sign is the fraud signal; abs() would delete it.

    Cheap structural guard, in the spirit of tests/test_layering.py -- an
    invariant this important should not live only in a docstring.
    """
    src = pathlib.Path(compare_amounts.__code__.co_filename)
    tree = ast.parse(src.read_text(encoding="utf-8"))
    calls = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert "abs" not in calls, "amount.py must never collapse the sign"
