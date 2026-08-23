"""Pydantic request and response contracts for the API stub."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from proofpay.core.compare.levels import Agreement as EvidenceAgreement
from proofpay.core.reasons import ReasonCode
from proofpay.core.reasons import Risk as RiskLevel
from proofpay.core.reasons import Status as VerificationStatus


class VerificationStage(StrEnum):
    COMPLETE = "COMPLETE"
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"


class MembershipRole(StrEnum):
    MERCHANT_ADMIN = "MERCHANT_ADMIN"
    MANAGER = "MANAGER"
    VERIFIER = "VERIFIER"
    REVIEWER = "REVIEWER"


class ReviewOutcome(StrEnum):
    UPHELD = "UPHELD"
    OVERRIDDEN = "OVERRIDDEN"
    MORE_EVIDENCE_REQUIRED = "MORE_EVIDENCE_REQUIRED"


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class ApiError(ApiModel):
    code: str
    message: str
    details: list[object] | None = None
    request_id: str | None = None


class EvidenceItem(ApiModel):
    field: str
    level_code: str
    label: str
    score: float = Field(ge=0.0, le=1.0)
    agreement: EvidenceAgreement
    claimed_value: object | None = None
    recorded_value: object | None = None
    detail: dict[str, object] = Field(default_factory=dict)


class PaymentClaimView(ApiModel):
    proof_id: str
    provider: str | None = None
    amount_minor: int | None = None
    currency: str = "PKR"
    sender_name: str | None = None
    receiver_name: str | None = None
    reference_id: str | None = None
    occurred_at: datetime | None = None


class TransactionView(ApiModel):
    id: str
    provider: str
    external_transaction_id: str
    amount_minor: int
    currency: str
    sender_name: str | None = None
    receiver_name: str | None = None
    occurred_at: datetime
    status: str
    source: str
    payment_account_id: str | None = None
    trust_level: str = "DEMO_TRUSTED"


class MatchedTransactionSummary(ApiModel):
    """Least-privilege transaction projection safe for a verifier or rider."""

    id: str
    provider: str
    masked_reference: str | None = None
    amount_minor: int
    currency: str
    occurred_at: datetime
    status: str


class OrderView(ApiModel):
    id: str
    external_order_ref: str
    expected_amount_minor: int
    currency: str
    status: str
    assigned_verifier_name: str | None = None
    created_at: datetime


class VerificationResult(ApiModel):
    id: str
    order_id: str | None = None
    status: VerificationStatus
    stage: VerificationStage
    risk: RiskLevel
    confidence: float = Field(ge=0.0, le=1.0)
    claim: PaymentClaimView
    matched_transaction: MatchedTransactionSummary | None = None
    matched_txn_id: str | None = None
    reasons: list[ReasonCode]
    summary: str
    fired_rule_id: str
    evidence: list[EvidenceItem]
    observations: list[str] = Field(default_factory=list)
    recommended_action: str
    ruleset_version: str
    policy_fingerprint: str
    engine_version: str
    evaluated_at: datetime
    created_at: datetime
    degraded: bool = False


class VerificationListItem(ApiModel):
    id: str
    order_id: str | None = None
    status: VerificationStatus
    risk: RiskLevel
    amount_minor: int | None = None
    currency: str = "PKR"
    provider: str | None = None
    sender_name: str | None = None
    created_at: datetime


class VerificationHistory(ApiModel):
    items: list[VerificationListItem]
    total: int


class OrderList(ApiModel):
    items: list[OrderView]
    total: int


class TransactionCreateRequest(ApiModel):
    provider: str
    external_transaction_id: str
    amount_minor: int = Field(gt=0)
    currency: str = Field(default="PKR", min_length=3, max_length=3)
    sender_name: str | None = None
    receiver_name: str | None = None
    occurred_at: datetime
    payment_account_id: str | None = None
    source_type: str = "DEMO"
    trust_level: str = "DEMO_TRUSTED"


class TransactionList(ApiModel):
    items: list[TransactionView]
    total: int


class DashboardSummary(ApiModel):
    total_checked: int
    by_status: dict[VerificationStatus, int]
    verified_amount_minor: int
    currency: str = "PKR"


class ReviewRequest(ApiModel):
    review_outcome: ReviewOutcome
    new_decision_status: VerificationStatus | None = None
    reason_code: str = Field(min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_override(self) -> ReviewRequest:
        if self.review_outcome is ReviewOutcome.OVERRIDDEN and self.new_decision_status is None:
            raise ValueError("new_decision_status is required when review_outcome is OVERRIDDEN")
        if (
            self.review_outcome is not ReviewOutcome.OVERRIDDEN
            and self.new_decision_status is not None
        ):
            raise ValueError("new_decision_status is only valid for OVERRIDDEN reviews")
        return self


class ReviewAssignmentView(ApiModel):
    id: str
    verification_id: str
    status: str
    assigned_to_role: MembershipRole
    created_at: datetime


class ReviewQueue(ApiModel):
    items: list[ReviewAssignmentView]
    total: int


class ManualReviewView(ApiModel):
    id: str
    verification_id: str
    previous_decision_status: VerificationStatus
    review_outcome: ReviewOutcome
    new_decision_status: VerificationStatus | None = None
    reason_code: str
    notes: str | None = None
    created_at: datetime


class DemoResetResponse(ApiModel):
    status: str
    reset_at: datetime


class TokenResponse(ApiModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 3600
    merchant_id: str
    role: MembershipRole
    scopes: list[str]


class UserResponse(ApiModel):
    id: str
    merchant_id: str
    display_name: str
    role: MembershipRole
    scopes: list[str]
