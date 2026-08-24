"""Verification attempts, evidence, candidates, and allocation invariants."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from proofpay.db.base import JSON_VARIANT, Base

from .enums import (
    AllocationStatus,
    EvidenceOutcome,
    RiskLevel,
    VerificationDecisionStatus,
    VerificationLifecycleStatus,
    enum_column,
)
from .types import CreatedAt, UpdatedAt, UuidPrimaryKey


class VerificationAttempt(Base):
    """One orchestration run and its reproducible persisted decision."""

    __tablename__ = "verification_attempts"

    id: Mapped[UuidPrimaryKey]
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    payment_proof_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    payment_claim_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    requested_by_membership_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    lifecycle_status: Mapped[VerificationLifecycleStatus] = enum_column(
        VerificationLifecycleStatus, default=VerificationLifecycleStatus.RECEIVED
    )
    decision_status: Mapped[VerificationDecisionStatus | None] = enum_column(
        VerificationDecisionStatus, nullable=True
    )
    risk_level: Mapped[RiskLevel | None] = enum_column(RiskLevel, nullable=True)
    decision_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    selected_transaction_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    rule_set_version: Mapped[str | None] = mapped_column(String(128))
    summary_reason_code: Mapped[str | None] = mapped_column(String(128))
    failure_code: Mapped[str | None] = mapped_column(String(128))
    failure_detail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[dt.datetime | None]
    decided_at: Mapped[dt.datetime | None]
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    __table_args__ = (
        UniqueConstraint("merchant_id", "id", name="uq_attempt_merchant_id"),
        UniqueConstraint(
            "merchant_id",
            "id",
            "selected_transaction_id",
            name="uq_attempt_selected_transaction",
        ),
        ForeignKeyConstraint(
            ["merchant_id", "order_id"],
            ["orders.merchant_id", "orders.id"],
            name="fk_attempt_order_same_merchant",
        ),
        ForeignKeyConstraint(
            ["merchant_id", "payment_proof_id"],
            ["payment_proofs.merchant_id", "payment_proofs.id"],
            name="fk_attempt_proof_same_merchant",
        ),
        ForeignKeyConstraint(
            ["merchant_id", "payment_claim_id"],
            ["payment_claims.merchant_id", "payment_claims.id"],
            name="fk_attempt_claim_same_merchant",
        ),
        ForeignKeyConstraint(
            ["merchant_id", "requested_by_membership_id"],
            ["merchant_memberships.merchant_id", "merchant_memberships.id"],
            name="fk_attempt_requester_same_merchant",
        ),
        ForeignKeyConstraint(
            ["merchant_id", "selected_transaction_id"],
            ["merchant_transactions.merchant_id", "merchant_transactions.id"],
            name="fk_attempt_selected_transaction_same_merchant",
        ),
        Index("ix_attempts_merchant_order_created", "merchant_id", "order_id", "created_at"),
        Index(
            "ix_attempts_merchant_decision_created",
            "merchant_id",
            "decision_status",
            "created_at",
        ),
    )


class MatchCandidate(Base):
    """One ranked merchant transaction considered by an attempt."""

    __tablename__ = "match_candidates"

    id: Mapped[UuidPrimaryKey]
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    verification_attempt_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    merchant_transaction_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    aggregate_score: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    field_scores: Mapped[dict[str, Any]] = mapped_column(JSON_VARIANT, nullable=False, default=dict)
    critical_conflicts: Mapped[dict[str, Any]] = mapped_column(
        JSON_VARIANT, nullable=False, default=dict
    )
    matcher_version: Mapped[str] = mapped_column(String(128), nullable=False)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[CreatedAt]

    __table_args__ = (
        UniqueConstraint(
            "verification_attempt_id",
            "merchant_transaction_id",
            name="uq_candidate_attempt_transaction",
        ),
        UniqueConstraint("verification_attempt_id", "rank", name="uq_candidate_attempt_rank"),
        ForeignKeyConstraint(
            ["merchant_id", "verification_attempt_id"],
            ["verification_attempts.merchant_id", "verification_attempts.id"],
            name="fk_candidate_attempt_same_merchant",
        ),
        ForeignKeyConstraint(
            ["merchant_id", "merchant_transaction_id"],
            ["merchant_transactions.merchant_id", "merchant_transactions.id"],
            name="fk_candidate_transaction_same_merchant",
        ),
        Index(
            "uq_candidate_selected_attempt",
            "verification_attempt_id",
            unique=True,
            sqlite_where=text("selected = 1"),
            postgresql_where=text("selected = true"),
        ),
    )


class EvidenceItem(Base):
    """A typed observation consumed by the deterministic decision engine."""

    __tablename__ = "evidence_items"

    id: Mapped[UuidPrimaryKey]
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    verification_attempt_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    evidence_code: Mapped[str] = mapped_column(String(128), nullable=False)
    outcome: Mapped[EvidenceOutcome] = enum_column(EvidenceOutcome, default=EvidenceOutcome.UNKNOWN)
    observed_value: Mapped[dict[str, Any] | None] = mapped_column(JSON_VARIANT)
    expected_value: Mapped[dict[str, Any] | None] = mapped_column(JSON_VARIANT)
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON_VARIANT)
    source_component: Mapped[str] = mapped_column(String(128), nullable=False)
    component_version: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[CreatedAt]

    __table_args__ = (
        ForeignKeyConstraint(
            ["merchant_id", "verification_attempt_id"],
            ["verification_attempts.merchant_id", "verification_attempts.id"],
            name="fk_evidence_attempt_same_merchant",
        ),
        CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 1)", name="evidence_score_range"
        ),
        Index("ix_evidence_merchant_attempt", "merchant_id", "verification_attempt_id"),
    )


class TransactionAllocation(Base):
    """The durable, concurrency-safe consumption of a transaction by an order."""

    __tablename__ = "transaction_allocations"

    id: Mapped[UuidPrimaryKey]
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    merchant_transaction_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    verification_attempt_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[AllocationStatus] = enum_column(
        AllocationStatus, default=AllocationStatus.ACTIVE
    )
    allocated_at: Mapped[CreatedAt]
    released_at: Mapped[dt.datetime | None]
    released_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    release_reason: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        ForeignKeyConstraint(
            ["merchant_id", "merchant_transaction_id"],
            ["merchant_transactions.merchant_id", "merchant_transactions.id"],
            name="fk_allocation_transaction_same_merchant",
        ),
        ForeignKeyConstraint(
            ["merchant_id", "order_id"],
            ["orders.merchant_id", "orders.id"],
            name="fk_allocation_order_same_merchant",
        ),
        ForeignKeyConstraint(
            ["merchant_id", "verification_attempt_id", "merchant_transaction_id"],
            [
                "verification_attempts.merchant_id",
                "verification_attempts.id",
                "verification_attempts.selected_transaction_id",
            ],
            name="fk_allocation_selected_transaction",
        ),
        ForeignKeyConstraint(
            ["merchant_id", "released_by_membership_id"],
            ["merchant_memberships.merchant_id", "merchant_memberships.id"],
            name="fk_allocation_releaser_same_merchant",
        ),
        Index(
            "uq_allocation_active_txn",
            "merchant_transaction_id",
            unique=True,
            sqlite_where=text("status = 'ACTIVE'"),
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        Index(
            "uq_allocation_active_order",
            "order_id",
            unique=True,
            sqlite_where=text("status = 'ACTIVE'"),
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        Index("ix_allocations_merchant_order_status", "merchant_id", "order_id", "status"),
        CheckConstraint(
            "(status = 'ACTIVE' AND released_at IS NULL "
            "AND released_by_membership_id IS NULL AND release_reason IS NULL) "
            "OR (status = 'RELEASED' AND released_at IS NOT NULL "
            "AND released_by_membership_id IS NOT NULL AND release_reason IS NOT NULL)",
            name="allocation_release_fields_consistent",
        ),
    )


__all__ = ["EvidenceItem", "MatchCandidate", "TransactionAllocation", "VerificationAttempt"]
