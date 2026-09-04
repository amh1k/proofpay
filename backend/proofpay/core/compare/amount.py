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
from decimal import Decimal
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
    "is_material_overpayment",
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
    overpayment_material_minor: int
    overpayment_material_pct: float


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
    #: Axis A's magnitude qualifier, and the mirror of `material_inflation` on
    #: axis B: the money arrived, nobody is lying, and far more of it arrived
    #: than the order asked for. Its own field rather than a number the rule
    #: table re-derives, so the threshold that produced it lives in the policy
    #: fingerprint and the audit trail records what the rule fired on.
    material_overpayment: bool = False
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
                # The magnitude qualifier follows from the arithmetic exactly as
                # the direction does, so it is derived here rather than carried
                # only by `R072`. It used to be `R072`'s alone, and that made a
                # large overpayment invisible whenever any rule above `R072`
                # took the claim: `R065` (an imported ledger row) and `R067` (a
                # field the reader was unsure of) both outrank it, and
                # `explain._summary` gates the overpayment sentence on this
                # code -- so a merchant sent to review over a Rs 5,000 payment
                # against a Rs 1,500 order was told only that part of the
                # screenshot was hard to read. Not one word that 3x the order
                # total had arrived and somebody would want it back.
                #
                # The sibling shortfall code has always been derived, which is
                # why the underpaid case never had this hole, and
                # `explain._summary` argues the principle in its own comment:
                # the merchant is owed both facts, not whichever one the
                # winning rule happens to be about.
                if self.material_overpayment:
                    codes.append(ReasonCode.AMOUNT_OVERPAID_MATERIAL)
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
    return inflation_minor >= _scaled(policy.inflation_material_pct, ledger_minor)


def is_material_overpayment(
    overpayment_minor: int, expected_minor: int, policy: AmountPolicy
) -> bool:
    """Is this overpayment big enough that a human should look at it?

    The commercial-axis mirror of ``is_material_inflation``, and deliberately
    the same shape: both knobs must be cleared (**and**, not **or**), so the
    judgement scales with the size of the order while keeping an absolute
    floor, and setting either knob to 0 disables that half cleanly.

    * ``overpayment_material_minor`` -- a floor. A customer rounding up, or
      adding delivery money on top, is not a case for a human.
    * ``overpayment_material_pct`` -- a proportion of the **order total**, not
      of what arrived. The question a merchant is deciding is "how much more
      than I asked for is this?", and the order total is the thing being asked
      about. (``is_material_inflation`` uses the ledger amount as its base
      because ``order.expected`` is not always on file *there*; here the
      comparison is meaningless without it, and ``AmountRelation.OVER`` already
      implies an expectation exists.)

    Why this is worth a rule at all: a customer paying Rs. 200 too much has
    covered the order and then some, and stopping that order to fetch a human
    costs more than the Rs. 200. A customer paying three times the order total
    has either fat-fingered a digit or sent another order's money, and in both
    cases somebody is going to ask for it back.
    """
    if overpayment_minor <= 0:
        return False
    if overpayment_minor < policy.overpayment_material_minor:
        return False

    # `Fraction`, not `pct * expected_minor`. The threshold is a float and the
    # amounts are exact paisa, so the obvious spelling converts money to a float
    # at the one point where the answer turns on a single minor unit. Above
    # 2**53 paisa that conversion rounds: at expected=9_007_199_254_740_993 an
    # overpayment one paisa SHORT of the cut-point compares equal to it, and a
    # non-material overpayment is reported as material. Nothing in the schema
    # rejects those amounts -- the column is a BigInteger -- so the only thing
    # standing between this and a wrong verdict was the size of Pakistani
    # receipts. Money never becomes a float, including here.
    return overpayment_minor >= _scaled(policy.overpayment_material_pct, expected_minor)


def _scaled(pct: float, base_minor: int) -> Decimal:
    """`pct` of `base_minor` paisa, without money ever becoming a float.

    The obvious spelling, `pct * base_minor`, converts an exact paisa count to a
    float at the one point where the answer turns on a single minor unit. Above
    2**53 paisa that conversion rounds, and a value one paisa BELOW the cut-point
    compares equal to it: at base=9_007_199_254_740_993 with pct=1.0, an
    insufficient overpayment is reported as material. Nothing rejects amounts
    that size -- the column is a BigInteger -- so the only thing between this and
    a wrong verdict was the size of Pakistani receipts.

    `Decimal(str(pct))` rather than `Decimal(pct)`: the second faithfully
    reproduces the float's own error, which is the thing being avoided. Going via
    the repr gives the number the policy author actually wrote.
    """
    return Decimal(str(pct)) * base_minor


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
        material_over = False
    else:
        shortfall = expected - ledger
        relation = _relation(shortfall.minor)
        tolerance = policy.amount_tolerance_minor
        # Written out rather than abs() so no reader mistakes this magnitude
        # test for the signed comparison above, which must never collapse.
        within_tolerance = -tolerance <= shortfall.minor <= tolerance
        # `shortfall` is signed: OVER means it is negative, so the overpayment
        # is its negation. Guarded on the relation rather than on the sign so
        # that an EXACT match can never be read as a zero-sized overpayment.
        material_over = relation is AmountRelation.OVER and is_material_overpayment(
            -shortfall.minor, expected.minor, policy
        )

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
        material_overpayment=material_over,
        observations=tuple(observations),
    )
