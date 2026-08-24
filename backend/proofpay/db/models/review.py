"""Scoped review assignments and append-only manual review decisions."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from proofpay.db.base import Base

from .enums import (
    ReviewAssignmentStatus,
    ReviewOutcome,
    VerificationDecisionStatus,
    enum_column,
)
from .types import CreatedAt, UuidPrimaryKey


class ReviewAssignment(Base):
    """Assigns one reviewable attempt to a scoped reviewer."""

    __tablename__ = "review_assignments"

    id: Mapped[UuidPrimaryKey]
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    verification_attempt_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    reviewer_membership_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[ReviewAssignmentStatus] = enum_column(
        ReviewAssignmentStatus, default=ReviewAssignmentStatus.OPEN
    )
    assigned_at: Mapped[CreatedAt]
    completed_at: Mapped[dt.datetime | None]

    __table_args__ = (
        ForeignKeyConstraint(
            ["merchant_id", "verification_attempt_id"],
            ["verification_attempts.merchant_id", "verification_attempts.id"],
            name="fk_review_assignment_attempt_same_merchant",
        ),
        ForeignKeyConstraint(
            ["merchant_id", "reviewer_membership_id"],
            ["merchant_memberships.merchant_id", "merchant_memberships.id"],
            name="fk_review_assignment_reviewer_same_merchant",
        ),
        Index(
            "uq_review_assignment_active_attempt",
            "verification_attempt_id",
            unique=True,
            sqlite_where=text("status IN ('OPEN', 'IN_PROGRESS')"),
            postgresql_where=text("status IN ('OPEN', 'IN_PROGRESS')"),
        ),
        Index(
            "ix_review_assignments_merchant_reviewer_status",
            "merchant_id",
            "reviewer_membership_id",
            "status",
        ),
    )


class ManualReview(Base):
    """An accountable human review or controlled decision override."""

    __tablename__ = "manual_reviews"

    id: Mapped[UuidPrimaryKey]
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    verification_attempt_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    reviewer_membership_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    previous_decision_status: Mapped[VerificationDecisionStatus | None] = enum_column(
        VerificationDecisionStatus, nullable=True
    )
    review_outcome: Mapped[ReviewOutcome] = enum_column(
        ReviewOutcome, default=ReviewOutcome.MORE_EVIDENCE_REQUIRED
    )
    new_decision_status: Mapped[VerificationDecisionStatus | None] = enum_column(
        VerificationDecisionStatus, nullable=True
    )
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[CreatedAt]

    __table_args__ = (
        ForeignKeyConstraint(
            ["merchant_id", "verification_attempt_id"],
            ["verification_attempts.merchant_id", "verification_attempts.id"],
            name="fk_manual_review_attempt_same_merchant",
        ),
        ForeignKeyConstraint(
            ["merchant_id", "reviewer_membership_id"],
            ["merchant_memberships.merchant_id", "merchant_memberships.id"],
            name="fk_manual_review_reviewer_same_merchant",
        ),
        CheckConstraint(
            "(review_outcome = 'OVERRIDDEN' AND new_decision_status IS NOT NULL) "
            "OR (review_outcome <> 'OVERRIDDEN' AND new_decision_status IS NULL)",
            name="manual_review_override_status_consistent",
        ),
        Index("ix_manual_reviews_merchant_attempt", "merchant_id", "verification_attempt_id"),
    )


__all__ = ["ManualReview", "ReviewAssignment"]
