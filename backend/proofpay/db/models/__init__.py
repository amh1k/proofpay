"""SQLAlchemy persistence models and their stable database-facing enums."""

# Import every model here so Base.metadata is complete for Alembic and tests.
from .audit import AuditEvent
from .commerce import MerchantTransaction, Order, PaymentAccount
from .enums import (
    AllocationStatus,
    BranchStatus,
    EvidenceOutcome,
    IdempotencyState,
    MembershipRole,
    MembershipScope,
    MembershipStatus,
    MerchantStatus,
    OrderStatus,
    PaymentAccountStatus,
    ProofRetentionStatus,
    ReviewAssignmentStatus,
    ReviewOutcome,
    RiskLevel,
    TransactionSourceType,
    TransactionStatus,
    TransactionTrustLevel,
    UserStatus,
    VerificationDecisionStatus,
    VerificationLifecycleStatus,
)
from .idempotency import IdempotencyRecord
from .identity import Branch, BranchMembership, Merchant, MerchantMembership, User
from .proof import PaymentClaim, PaymentProof
from .review import ManualReview, ReviewAssignment
from .verification import (
    EvidenceItem,
    MatchCandidate,
    TransactionAllocation,
    VerificationAttempt,
)

__all__ = [
    "AllocationStatus",
    "AuditEvent",
    "Branch",
    "BranchMembership",
    "BranchStatus",
    "EvidenceItem",
    "EvidenceOutcome",
    "IdempotencyRecord",
    "IdempotencyState",
    "ManualReview",
    "MatchCandidate",
    "MembershipRole",
    "MembershipScope",
    "MembershipStatus",
    "Merchant",
    "MerchantMembership",
    "MerchantStatus",
    "MerchantTransaction",
    "Order",
    "OrderStatus",
    "PaymentAccount",
    "PaymentAccountStatus",
    "PaymentClaim",
    "PaymentProof",
    "ProofRetentionStatus",
    "ReviewAssignment",
    "ReviewAssignmentStatus",
    "ReviewOutcome",
    "RiskLevel",
    "TransactionAllocation",
    "TransactionSourceType",
    "TransactionStatus",
    "TransactionTrustLevel",
    "User",
    "UserStatus",
    "VerificationAttempt",
    "VerificationDecisionStatus",
    "VerificationLifecycleStatus",
]
