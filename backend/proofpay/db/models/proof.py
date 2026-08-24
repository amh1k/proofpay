"""Immutable uploaded proof metadata and extracted payment claims."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from proofpay.db.base import JSON_VARIANT, Base

from .enums import ProofRetentionStatus, enum_column
from .types import CreatedAt, UuidPrimaryKey


class PaymentProof(Base):
    """Validated metadata for a private screenshot or payment image."""

    __tablename__ = "payment_proofs"

    id: Mapped[UuidPrimaryKey]
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uploaded_by_membership_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    width_px: Mapped[int] = mapped_column(Integer, nullable=False)
    height_px: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    perceptual_hash: Mapped[str | None] = mapped_column(String(128))
    retention_status: Mapped[ProofRetentionStatus] = enum_column(
        ProofRetentionStatus, default=ProofRetentionStatus.ACTIVE
    )
    uploaded_at: Mapped[CreatedAt]
    deleted_at: Mapped[dt.datetime | None]

    __table_args__ = (
        UniqueConstraint("merchant_id", "id", name="uq_proof_merchant_id"),
        Index("ix_proofs_merchant_uploaded_at", "merchant_id", "uploaded_at"),
        Index("ix_proofs_merchant_sha256", "merchant_id", "sha256_hash", unique=True),
        ForeignKeyConstraint(
            ["merchant_id", "uploaded_by_membership_id"],
            ["merchant_memberships.merchant_id", "merchant_memberships.id"],
            name="fk_proof_uploader_same_merchant",
        ),
    )


class PaymentClaim(Base):
    """One immutable parser interpretation of a payment proof."""

    __tablename__ = "payment_claims"

    id: Mapped[UuidPrimaryKey]
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    payment_proof_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    provider_code: Mapped[str | None] = mapped_column(String(64))
    claimed_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(3))
    sender_name: Mapped[str | None] = mapped_column(String(255))
    receiver_name: Mapped[str | None] = mapped_column(String(255))
    external_transaction_id: Mapped[str | None] = mapped_column(String(255))
    claimed_occurred_at: Mapped[dt.datetime | None]
    timestamp_raw: Mapped[str | None] = mapped_column(String(255))
    timezone_assumption: Mapped[str | None] = mapped_column(String(64))
    field_confidences: Mapped[dict[str, Any]] = mapped_column(
        JSON_VARIANT, nullable=False, default=dict
    )
    raw_ocr_text: Mapped[str | None] = mapped_column(Text)
    provider_template: Mapped[str | None] = mapped_column(String(128))
    parser_version: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[CreatedAt]

    __table_args__ = (
        UniqueConstraint("merchant_id", "id", name="uq_claim_merchant_id"),
        ForeignKeyConstraint(
            ["merchant_id", "payment_proof_id"],
            ["payment_proofs.merchant_id", "payment_proofs.id"],
            name="fk_claim_proof_same_merchant",
        ),
        Index("ix_claims_merchant_proof", "merchant_id", "payment_proof_id"),
    )


__all__ = ["PaymentClaim", "PaymentProof"]
