"""Deterministic example data used until persistence is implemented.

TWO KINDS OF DATA LIVE HERE, AND THEY HAVE DIFFERENT RULES:

  1. The ORDER ROWS served by GET /orders are *derived*, not written.  They are
     projected out of `proofpay.api.engine_demo`, which is the module the real
     decision engine is actually handed when a screenshot arrives.  See
     `_order_view` below for why they are not simply typed out again.

  2. Everything else (the example transaction, claim, evidence and the five
     history rows) is still hand-written illustration.  It is never evaluated
     by the engine — it exists so the history and dashboard screens have
     something to show before any real check has been run.

     One exception, and it is deliberate: the three PROVENANCE stamps on those
     rows (`ruleset_version`, `policy_fingerprint`, `engine_version`) are
     derived from the live engine rather than typed out.  See
     `_STUB_POLICY_FINGERPRINT` below for what typing them out cost.

WHY THERE ARE TWO CLOCKS IN THIS FILE:
    `_time()` below pins the illustrative rows to 2026-08-23.  The derived
    order rows carry engine_demo's timestamps instead, which are offsets from
    `demo.clock.PINNED_ANCHOR` (2026-08-20 14:05 PKT).  That mismatch is the
    price of deriving: an order's created_at must be the one the engine
    compares receipt timestamps against, not a second date invented here that
    happens to look tidier next to the history rows.  Do not "fix" it by
    re-stamping the derived rows with `_time()` — that reintroduces exactly the
    drift the derivation exists to prevent.
"""

from __future__ import annotations

from datetime import UTC, datetime

from proofpay.api.engine_demo import DemoEngineCase, demo_cases
from proofpay.core.decide import ENGINE_VERSION, RULESET_VERSION, DecisionPolicy
from proofpay.core.reasons import ReasonCode

from .auth import DEMO_VERIFIER
from .schemas import (
    DashboardSummary,
    EvidenceAgreement,
    EvidenceItem,
    MatchedTransactionSummary,
    OrderView,
    PaymentClaimView,
    RiskLevel,
    TransactionView,
    VerificationHistory,
    VerificationListItem,
    VerificationResult,
    VerificationStage,
    VerificationStatus,
)


def _time(hour: int, minute: int) -> datetime:
    return datetime(2026, 8, 23, hour, minute, tzinfo=UTC)


# The one thing on an illustrative row that is NOT invented here.  The three
# provenance stamps below say which rules, which thresholds and which pipeline
# produced a verdict, and a merchant comparing a history row against a live
# check reads them side by side.  Typed out by hand they were
# "rules/2026-08-22.1" / "policy-demo-v1" / "engine-1.0.0" — a ruleset that
# never existed, a fingerprint no `DecisionPolicy` can ever hash to, and an
# engine version four releases stale.  Nothing failed when the real values
# moved, because a literal cannot go stale loudly.
#
# Derived, they track.  `DecisionPolicy()` is the same default the endpoint in
# `verifications.py` hands to `decide()`, so a history row and a fresh check
# now agree on their provenance line instead of contradicting it on screen.
_STUB_POLICY_FINGERPRINT = DecisionPolicy().fingerprint()


DEMO_TRANSACTION = TransactionView(
    id="txn_demo_1001",
    provider="easypaisa",
    external_transaction_id="TX1001",
    amount_minor=200_000,
    currency="PKR",
    sender_name="M. Ali",
    receiver_name="ProofPay Store",
    occurred_at=_time(11, 42),
    status="POSTED",
    source="DEMO",
)

# Every demo order is waiting for its payment to be checked — that is the whole
# reason it is in the picker.  The status is therefore the same on all five, and
# deliberately so: a per-order status like "DISPUTED" or "PAID" would announce
# the verdict on the button before the merchant has uploaded anything, and the
# demo's entire point is that the answer comes out of the engine, not out of a
# label someone typed next to the order.
_ORDER_STATUS = "PAYMENT_REVIEW"


def _order_view(case: DemoEngineCase) -> OrderView:
    """Project one engine case into the order row the merchant picks from.

        engine_demo._CASES  ──derive──>  STUB_ORDERS  ──GET /orders──>  picker
                │                                                         │
                └────────────── POST /verifications ──────────────────────┘
                        (the same case, evaluated for real)

    The picker and the verdict must be talking about the same order.  Typing
    the five orders out again here would let the two halves drift apart on the
    only two fields the merchant can actually read — the reference and the
    expected amount — and the failure would surface on stage: a button labelled
    "ORD-S01 · Rs 5,000" whose verdict then explains that Rs 500 was expected.
    Deriving makes that class of bug unrepresentable.

    The projection lives here, not in `engine_demo`, because there is no import
    cycle to dodge (engine_demo imports only the frozen core and the clock) and
    the direction that keeps engine_demo free of Pydantic and of API schemas is
    the better one: the engine's demo inputs should not have to know that an
    HTTP contract exists.

    The two guards below are not defensive noise.  `OrderView.external_order_ref`
    and `.expected_amount_minor` are required, while `core.models.Order` allows
    both to be None (a proof can legitimately arrive with no order attached).  A
    case added without them would otherwise fail as an opaque Pydantic error at
    import time, taking the whole app down with a message that names a field
    rather than the case that is missing it.
    """
    order = case.order
    if order.expected is None or order.reference is None:
        raise ValueError(
            f"demo case {order.order_id!r} cannot be shown to a merchant: an order in the "
            "picker needs both a reference and an expected amount"
        )
    if order.created_at is None:
        raise ValueError(f"demo case {order.order_id!r} has no created_at to show")

    return OrderView(
        id=order.order_id,
        external_order_ref=order.reference,
        expected_amount_minor=order.expected.minor,
        currency=order.expected.currency,
        status=_ORDER_STATUS,
        # Only the orders the VERIFIER can actually reach carry a verifier's
        # name.  Naming a rider on an order they would get a 404 for would put a
        # falsehood on screen, and the name is read from the principal itself so
        # the label and the role boundary cannot fall out of step.
        assigned_verifier_name=(
            DEMO_VERIFIER.display_name
            if order.order_id in DEMO_VERIFIER.assigned_order_ids
            else None
        ),
        created_at=order.created_at,
    )


# Order preserved exactly as engine_demo declares it; see the presentation-order
# comment there.  The frontend renders these as a row of buttons, so the index
# of each order has to be the same on every run and on every machine.
STUB_ORDERS = [_order_view(case) for case in demo_cases()]


def _demo_order(order_id: str) -> OrderView:
    """Return the one derived order the illustrative rows below hang off.

    By id, and deliberately not `STUB_ORDERS[0]`.  The presentation-order
    comment in `engine_demo` explicitly invites reordering the cases, and an
    index would follow that silently: move `order_demo_1002` to the front and
    the Rs 2,000 easypaisa illustration below, plus the history row the rider is
    allowed to see, would quietly re-attach themselves to the edited-amount
    order.  Nothing would fail; the screens would just start describing a
    different order.  A lookup says which order is meant, and says it loudly
    when that order is gone.
    """
    for order in STUB_ORDERS:
        if order.id == order_id:
            return order
    raise ValueError(
        f"{order_id!r} is no longer a demo case, so the example claim, evidence and "
        "history rows below have nothing to hang off"
    )


DEMO_ORDER = _demo_order("order_demo_1001")

DEMO_CLAIM = PaymentClaimView(
    proof_id="proof_demo_1001",
    provider="easypaisa",
    amount_minor=200_000,
    currency="PKR",
    sender_name="Muhammad Ali",
    receiver_name="ProofPay Store",
    reference_id="TX1001",
    occurred_at=_time(11, 42),
)

DEMO_EVIDENCE = [
    EvidenceItem(
        field="reference_id",
        level_code="REF_EXACT",
        label="Transaction ID matches exactly",
        score=1.0,
        agreement=EvidenceAgreement.AGREE,
        claimed_value="TX1001",
        recorded_value="TX1001",
        detail={"claimed": "TX1001", "matched": "TX1001"},
    ),
    EvidenceItem(
        field="amount",
        level_code="AMOUNT_EXACT",
        label="Amount matches the received transaction",
        score=1.0,
        agreement=EvidenceAgreement.AGREE,
        claimed_value=200_000,
        recorded_value=200_000,
        detail={"claimed_minor": 200_000, "received_minor": 200_000},
    ),
    EvidenceItem(
        field="sender_name",
        level_code="NAME_INITIALS",
        label="Match with initials expanded",
        score=0.91,
        agreement=EvidenceAgreement.WEAK,
        claimed_value="Muhammad Ali",
        recorded_value="M. Ali",
        detail={"claimed": "Muhammad Ali", "matched": "M. Ali"},
    ),
    EvidenceItem(
        field="timestamp",
        level_code="TIME_WITHIN_TOLERANCE",
        label="Timestamp is within the accepted window",
        score=0.98,
        agreement=EvidenceAgreement.AGREE,
        claimed_value="11:42:00Z",
        recorded_value="11:42:12Z",
        detail={"difference_seconds": 12},
    ),
]

DEMO_VERIFICATION = VerificationResult(
    id="verification_demo_1001",
    order_id=DEMO_ORDER.id,
    status=VerificationStatus.VERIFIED,
    stage=VerificationStage.COMPLETE,
    risk=RiskLevel.LOW,
    confidence=0.97,
    claim=DEMO_CLAIM,
    matched_transaction=MatchedTransactionSummary(
        id=DEMO_TRANSACTION.id,
        provider=DEMO_TRANSACTION.provider,
        masked_reference="TX••••01",
        amount_minor=DEMO_TRANSACTION.amount_minor,
        currency=DEMO_TRANSACTION.currency,
        occurred_at=DEMO_TRANSACTION.occurred_at,
        status=DEMO_TRANSACTION.status,
    ),
    matched_txn_id=DEMO_TRANSACTION.id,
    reasons=[
        ReasonCode.AMOUNT_EXACT,
        ReasonCode.CLAIM_CONSISTENT,
        ReasonCode.STRONG_FIELD_AGREEMENT,
    ],
    summary="The claimed payment matches a trusted transaction record.",
    fired_rule_id="R090",
    evidence=DEMO_EVIDENCE,
    recommended_action="Payment verified. Continue the order.",
    ruleset_version=RULESET_VERSION,
    policy_fingerprint=_STUB_POLICY_FINGERPRINT,
    engine_version=ENGINE_VERSION,
    evaluated_at=_time(11, 43),
    created_at=_time(11, 43),
)

DEMO_VERIFICATIONS = [
    DEMO_VERIFICATION,
    DEMO_VERIFICATION.model_copy(
        update={
            "id": "verification_demo_1002",
            "status": VerificationStatus.SUSPICIOUS,
            "risk": RiskLevel.HIGH,
            "confidence": 0.97,
            "claim": DEMO_CLAIM.model_copy(update={"amount_minor": 500_000}),
            "reasons": [ReasonCode.CLAIM_INFLATED, ReasonCode.AMOUNT_UNDERPAID],
            "summary": "The screenshot claims more than the trusted transaction received.",
            "fired_rule_id": "R030",
            "evidence": [
                *DEMO_EVIDENCE[:1],
                EvidenceItem(
                    field="amount",
                    level_code="AMOUNT_CONTRADICTED",
                    label="Claimed amount is greater than the received amount",
                    score=0.05,
                    agreement=EvidenceAgreement.CONTRADICT,
                    claimed_value=500_000,
                    recorded_value=200_000,
                    detail={"claimed_minor": 500_000, "received_minor": 200_000},
                ),
            ],
            "recommended_action": "Do not approve the order yet.",
        }
    ),
    DEMO_VERIFICATION.model_copy(
        update={
            "id": "verification_demo_1003",
            "status": VerificationStatus.DUPLICATE,
            "risk": RiskLevel.HIGH,
            "confidence": 1.0,
            "reasons": [ReasonCode.TXN_ALREADY_ALLOCATED],
            "summary": "This trusted transaction is already allocated to another order.",
            "fired_rule_id": "R020",
            "recommended_action": "Do not reuse this payment. Review the previous order.",
        }
    ),
    DEMO_VERIFICATION.model_copy(
        update={
            "id": "verification_demo_1004",
            "order_id": None,
            "status": VerificationStatus.NEEDS_REVIEW,
            "risk": RiskLevel.MEDIUM,
            "confidence": 0.62,
            "matched_txn_id": None,
            "matched_transaction": None,
            "reasons": [ReasonCode.AMBIGUOUS_CANDIDATES],
            "summary": "Multiple possible transactions require a human decision.",
            "fired_rule_id": "R050",
            "recommended_action": "Review the possible transactions manually.",
        }
    ),
    DEMO_VERIFICATION.model_copy(
        update={
            "id": "verification_demo_1005",
            "order_id": DEMO_ORDER.id,
            "status": VerificationStatus.UNMATCHED,
            "risk": RiskLevel.MEDIUM,
            "confidence": 0.42,
            "matched_txn_id": None,
            "matched_transaction": None,
            "reasons": [ReasonCode.NO_CANDIDATES],
            "summary": "No trusted transaction currently matches this payment claim.",
            "fired_rule_id": "R010",
            "recommended_action": "Wait for the transaction feed or check the payment details.",
        }
    ),
]

STUB_HISTORY = VerificationHistory(
    items=[
        VerificationListItem(
            id=item.id,
            order_id=item.order_id,
            status=item.status,
            risk=item.risk,
            amount_minor=item.claim.amount_minor,
            currency=item.claim.currency,
            provider=item.claim.provider,
            sender_name=item.claim.sender_name,
            created_at=item.created_at,
        )
        for item in DEMO_VERIFICATIONS
    ],
    total=len(DEMO_VERIFICATIONS),
)

STUB_DASHBOARD = DashboardSummary(
    total_checked=46,
    by_status={
        VerificationStatus.VERIFIED: 38,
        VerificationStatus.UNMATCHED: 3,
        VerificationStatus.SUSPICIOUS: 2,
        VerificationStatus.DUPLICATE: 2,
        VerificationStatus.NEEDS_REVIEW: 1,
    },
    verified_amount_minor=7_450_000,
)

# STUB_ORDERS is defined near the top of this module, not here beside its
# sibling, because DEMO_VERIFICATION above needs DEMO_ORDER to exist first.
STUB_TRANSACTIONS = [DEMO_TRANSACTION]


def verification_by_id(verification_id: str) -> VerificationResult | None:
    return next((item for item in DEMO_VERIFICATIONS if item.id == verification_id), None)
