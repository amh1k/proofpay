"""Deterministic example data used until persistence is implemented."""

from __future__ import annotations

from datetime import UTC, datetime

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

DEMO_ORDER = OrderView(
    id="order_demo_1001",
    external_order_ref="ORD-1001",
    expected_amount_minor=200_000,
    currency="PKR",
    status="PAYMENT_REVIEW",
    assigned_verifier_name="Ali Khan",
    created_at=_time(11, 30),
)

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
    reasons=["AMOUNT_EXACT", "CLAIM_CONSISTENT", "STRONG_FIELD_AGREEMENT"],
    summary="The claimed payment matches a trusted transaction record.",
    fired_rule_id="R020",
    evidence=DEMO_EVIDENCE,
    recommended_action="Payment verified. Continue the order.",
    ruleset_version="rules/2026-08-22.1",
    policy_fingerprint="policy-demo-v1",
    engine_version="engine-1.0.0",
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
            "reasons": ["CLAIM_INFLATED", "AMOUNT_UNDERPAID"],
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
            "reasons": ["TXN_ALREADY_ALLOCATED"],
            "summary": "This trusted transaction is already allocated to another order.",
            "fired_rule_id": "R040",
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
            "reasons": ["AMBIGUOUS_CANDIDATES"],
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
            "reasons": ["NO_CANDIDATES"],
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

STUB_ORDERS = [DEMO_ORDER]
STUB_TRANSACTIONS = [DEMO_TRANSACTION]


def verification_by_id(verification_id: str) -> VerificationResult | None:
    return next((item for item in DEMO_VERIFICATIONS if item.id == verification_id), None)
