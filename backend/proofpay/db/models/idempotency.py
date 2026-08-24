"""Durable request deduplication records scoped to a merchant."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from proofpay.db.base import JSON_VARIANT, Base

from .enums import IdempotencyState, enum_column
from .types import CreatedAt, UuidPrimaryKey


class IdempotencyRecord(Base):
    """Binds one idempotency key to one canonical request fingerprint."""

    __tablename__ = "idempotency_records"

    id: Mapped[UuidPrimaryKey]
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    verification_attempt_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    state: Mapped[IdempotencyState] = enum_column(
        IdempotencyState, default=IdempotencyState.IN_PROGRESS
    )
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSON_VARIANT)
    created_at: Mapped[CreatedAt]
    expires_at: Mapped[dt.datetime]

    __table_args__ = (
        UniqueConstraint("merchant_id", "idempotency_key", name="uq_idempotency_merchant_key"),
        ForeignKeyConstraint(
            ["merchant_id", "verification_attempt_id"],
            ["verification_attempts.merchant_id", "verification_attempts.id"],
            name="fk_idempotency_attempt_same_merchant",
        ),
        CheckConstraint(
            "state = 'IN_PROGRESS' OR verification_attempt_id IS NOT NULL",
            name="idempotency_completed_attempt_required",
        ),
        Index("ix_idempotency_expiry", "merchant_id", "expires_at"),
    )


__all__ = ["IdempotencyRecord"]
