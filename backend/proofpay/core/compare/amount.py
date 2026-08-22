"""Amount semantics: three amounts, two independent comparisons.

Guide section 5. Most reconciliation systems compare two numbers and lose the
fraud signal. There are three:

* ``order.expected`` -- what the merchant asked for
* ``ledger.amount``  -- **source of truth**, what actually arrived
* ``claim.amount``   -- what the screenshot asserts

and they answer two different questions:

**A. ledger vs expected -- a commercial outcome.** Did the customer pay the
right amount? Underpaid, overpaid, or exact. Nobody is lying; the books just
do not balance.

**B. claim vs ledger -- an integrity signal.** Does the screenshot agree with
the money? A screenshot asserting *more* than arrived is the core attack this
product exists to catch.

Both comparisons are signed. ``abs()`` appears nowhere in this module: the
sign *is* the fraud signal, and collapsing ``claim > ledger`` together with
``claim < ledger`` throws away the only thing that distinguishes an attacker
from a blurry photo.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from proofpay.core.money import Money
from proofpay.core.reasons import ObservationCode, ReasonCode

__all__ = [
    "AmountEvidence",
    "AmountPolicy",
    "AmountRelation",
    "ClaimIntegrity",
    "compare_amounts",
    "is_material_inflation",
    "is_power_of_ten_multiple",
]


class AmountPolicy(Protocol):
    """The slice of ``DecisionPolicy`` this module reads.

    Declared structurally so ``core.compare`` never imports ``core.decide``:
    comparisons are consumed by the decision engine, not the other way round.
    ``DecisionPolicy`` satisfies this by carrying the fields; nothing registers.
    """

    amount_tolerance_minor: int
    inflation_material_minor: int
    inflation_material_pct: float


class AmountRelation(StrEnum):
    """Commercial outcome of ledger vs the order total. Stable machine codes."""

    EXACT = "EXACT"
    UNDER = "UNDER"
    OVER = "OVER"
    UNKNOWN = "UNKNOWN"  # no order total on file -- see compare_amounts()


class ClaimIntegrity(StrEnum):
    """Agreement between the screenshot and the money. Stable machine codes."""

    CONSISTENT = "CONSISTENT"
    INFLATED = "INFLATED"
    DEFLATED = "DEFLATED"
    UNKNOWN = "UNKNOWN"  # amount unreadable on the proof -- see compare_amounts()


@dataclass(frozen=True, slots=True)
class AmountEvidence:
    """The full amount picture, in one immutable value.

    ``shortfall`` and ``inflation`` are ``None`` exactly when the corresponding
    relation is ``UNKNOWN``; there is no honest number to report, and a zero
    would read as "no discrepancy" in the evidence drawer.
    """

    relation: AmountRelation
    integrity: ClaimIntegrity
    shortfall: Money | None  # expected - ledger; positive means underpaid
    inflation: Money | None  # claim - ledger; positive means the proof over-claims
    within_tolerance: bool  # shortfall inside policy.amount_tolerance_minor
    material_inflation: bool = False  # big enough to accuse someone over
    observations: tuple[str, ...] = ()  # neutral notes, ObservationCode values

    @property
    def expected_known(self) -> bool:
        return self.relation is not AmountRelation.UNKNOWN

    @property
    def claim_known(self) -> bool:
        return self.integrity is not ClaimIntegrity.UNKNOWN

    @property
    def reason_codes(self) -> tuple[ReasonCode, ...]:
        """Reason codes implied by the arithmetic, commercial axis first.

        The rule table adds its own; these are the ones that follow from the
        numbers alone, so the explainer can render evidence without
        re-deriving anything.
        """
        codes: list[ReasonCode] = []
        match self.relation:
            case AmountRelation.EXACT:
                codes.append(ReasonCode.AMOUNT_EXACT)
            case AmountRelation.UNDER:
                codes.append(ReasonCode.AMOUNT_UNDERPAID)
            case AmountRelation.OVER:
                codes.append(ReasonCode.AMOUNT_OVERPAID)
            case AmountRelation.UNKNOWN:
                codes.append(ReasonCode.MISSING_ORDER_AMOUNT)
        match self.integrity:
            case ClaimIntegrity.CONSISTENT:
                codes.append(ReasonCode.CLAIM_CONSISTENT)
            case ClaimIntegrity.INFLATED:
                codes.append(ReasonCode.CLAIM_INFLATED)
            case ClaimIntegrity.DEFLATED:
                codes.append(ReasonCode.CLAIM_DEFLATED)
            case ClaimIntegrity.UNKNOWN:
                pass  # an unreadable amount asserts nothing, for or against
        return tuple(codes)


def _relation(shortfall_minor: int) -> AmountRelation:
    if shortfall_minor == 0:
        return AmountRelation.EXACT
    return AmountRelation.UNDER if shortfall_minor > 0 else AmountRelation.OVER


def _integrity(inflation_minor: int) -> ClaimIntegrity:
    if inflation_minor == 0:
        return ClaimIntegrity.CONSISTENT
    return ClaimIntegrity.INFLATED if inflation_minor > 0 else ClaimIntegrity.DEFLATED


def is_material_inflation(
    inflation_minor: int, ledger_minor: int, policy: AmountPolicy
) -> bool:
    """Is this over-claim worth calling suspicious?

    Guide section 5: ``claim - ledger = 100 paisa`` on a 5000-rupee order is an
    OCR artefact; 500000 paisa is an attack. Both policy knobs must be cleared
    (**and**, not **or**) so the judgement scales with the size of the payment
    while keeping an absolute floor:

    * ``inflation_material_minor`` -- a floor, so a 1% slip on a tiny order is
      not an accusation.
    * ``inflation_material_pct`` -- a proportion of what actually arrived, so a
      fixed floor does not flag rounding noise on a six-figure transfer.

    Setting either knob to 0 disables that half cleanly, which is why the
    conjunction is the right way round. Deflation is never material: OCR drops
    digits, attackers do not under-claim.
    """
    if inflation_minor <= 0:
        return False
    if inflation_minor < policy.inflation_material_minor:
        return False
    # Fraction of the money that actually arrived. ledger is present in every
    # call; order.expected is not, so it is the only base always available.
    return inflation_minor >= policy.inflation_material_pct * ledger_minor


def is_power_of_ten_multiple(claim_minor: int, ledger_minor: int) -> bool:
    """Is the claim exactly the ledger amount with zeros appended?

    Rs. 500 arrives, the proof says Rs. 5,000. OCR losing a trailing zero
    produces *deflation*, so an exact 10x/100x *inflation* is not a scanning
    artefact -- it is a digit typed in by hand. Cheap to compute and rare
    enough among honest receipts to be worth flagging.
    """
    if ledger_minor <= 0 or claim_minor <= ledger_minor:
        return False
    quotient, remainder = divmod(claim_minor, ledger_minor)
    if remainder:
        return False
    while quotient % 10 == 0:
        quotient //= 10
    return quotient == 1


def compare_amounts(
    expected: Money | None,
    ledger: Money,
    claim: Money | None,
    policy: AmountPolicy,
) -> AmountEvidence:
    """Run both amount comparisons against the ledger, the source of truth.

    ``expected`` is ``None`` when the order carries no total (an ad-hoc
    payment); ``claim`` is ``None`` when the proof's amount was unreadable.
    Neither is an error and neither may crash. Both degrade to ``UNKNOWN``
    rather than to a zero difference: an absent comparison must not be able to
    masquerade as a passing one anywhere downstream.

    All arithmetic is integer minor units in ``ledger``'s currency; ``Money``
    raises on a currency mismatch rather than silently comparing rupees to
    dollars.
    """
    observations: list[str] = []

    if expected is None:
        relation = AmountRelation.UNKNOWN
        shortfall: Money | None = None
        # No expectation exists, so no tolerance can be breached. This keeps
        # the underpayment rule from firing on an order that never named a
        # price; MISSING_ORDER_AMOUNT carries the caveat instead.
        within_tolerance = True
    else:
        shortfall = expected - ledger
        relation = _relation(shortfall.minor)
        tolerance = policy.amount_tolerance_minor
        # Written out rather than abs() so no reader mistakes this magnitude
        # test for the signed comparison above, which must never collapse.
        within_tolerance = -tolerance <= shortfall.minor <= tolerance

    if claim is None:
        integrity = ClaimIntegrity.UNKNOWN
        inflation: Money | None = None
        material = False
    else:
        inflation = claim - ledger
        integrity = _integrity(inflation.minor)
        material = is_material_inflation(inflation.minor, ledger.minor, policy)
        if integrity is ClaimIntegrity.INFLATED and is_power_of_ten_multiple(
            claim.minor, ledger.minor
        ):
            observations.append(ObservationCode.CLAIM_INFLATED_ROUND)

    return AmountEvidence(
        relation=relation,
        integrity=integrity,
        shortfall=shortfall,
        inflation=inflation,
        within_tolerance=within_tolerance,
        material_inflation=material,
        observations=tuple(observations),
    )
