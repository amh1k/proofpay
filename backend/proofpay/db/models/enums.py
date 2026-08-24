"""Stable persistence enum values defined by the data model."""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import mapped_column

from proofpay.core.reasons import Risk as RiskLevel
from proofpay.core.reasons import Status as VerificationDecisionStatus


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISABLED = "DISABLED"


class MerchantStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class MembershipRole(StrEnum):
    MERCHANT_ADMIN = "MERCHANT_ADMIN"
    MANAGER = "MANAGER"
    VERIFIER = "VERIFIER"
    REVIEWER = "REVIEWER"


class MembershipScope(StrEnum):
    MERCHANT_WIDE = "MERCHANT_WIDE"
    BRANCHES = "BRANCHES"
    ASSIGNED_RESOURCES = "ASSIGNED_RESOURCES"


class MembershipStatus(StrEnum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class BranchStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class OrderStatus(StrEnum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PAYMENT_REVIEW = "PAYMENT_REVIEW"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class PaymentAccountStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class ProofRetentionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PENDING_DELETE = "PENDING_DELETE"
    DELETED = "DELETED"


class VerificationLifecycleStatus(StrEnum):
    RECEIVED = "RECEIVED"
    VALIDATING = "VALIDATING"
    PROCESSING = "PROCESSING"
    DECIDED = "DECIDED"
    REVIEWED = "REVIEWED"
    FAILED = "FAILED"


class EvidenceOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    UNKNOWN = "UNKNOWN"


class AllocationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class ReviewAssignmentStatus(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReviewOutcome(StrEnum):
    UPHELD = "UPHELD"
    OVERRIDDEN = "OVERRIDDEN"
    MORE_EVIDENCE_REQUIRED = "MORE_EVIDENCE_REQUIRED"


class IdempotencyState(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class TransactionStatus(StrEnum):
    POSTED = "POSTED"
    PENDING = "PENDING"
    REVERSED = "REVERSED"


class TransactionSourceType(StrEnum):
    PROVIDER = "PROVIDER"
    WEBHOOK = "WEBHOOK"
    CSV = "CSV"
    MANUAL = "MANUAL"
    DEMO = "DEMO"


class TransactionTrustLevel(StrEnum):
    TRUSTED = "TRUSTED"
    PARTIAL = "PARTIAL"
    DEMO_TRUSTED = "DEMO_TRUSTED"


def enum_column(
    enum_type: type[StrEnum], *, default: StrEnum | None = None, nullable: bool = False
):
    """Create a portable, validated string enum column.

    SQLite has no native enum type. A named CHECK constraint keeps development
    and production equally strict while avoiding database-specific model code.
    """
    column_kwargs: dict[str, object] = {"nullable": nullable}
    if default is not None:
        column_kwargs["default"] = default
    return mapped_column(
        SqlEnum(
            enum_type,
            name=enum_type.__name__.lower(),
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        **column_kwargs,
    )


__all__ = [
    "AllocationStatus",
    "BranchStatus",
    "EvidenceOutcome",
    "IdempotencyState",
    "MembershipRole",
    "MembershipScope",
    "MembershipStatus",
    "MerchantStatus",
    "OrderStatus",
    "PaymentAccountStatus",
    "ProofRetentionStatus",
    "ReviewAssignmentStatus",
    "ReviewOutcome",
    "RiskLevel",
    "TransactionSourceType",
    "TransactionStatus",
    "TransactionTrustLevel",
    "UserStatus",
    "VerificationDecisionStatus",
    "VerificationLifecycleStatus",
    "enum_column",
]
