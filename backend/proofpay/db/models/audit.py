"""Append-only, privacy-aware security and decision history events."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, ForeignKeyConstraint, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from proofpay.db.base import JSON_VARIANT, Base

from .types import CreatedAt, UuidPrimaryKey


class AuditEvent(Base):
    """A redacted event describing a security or decision-history action."""

    __tablename__ = "audit_events"

    id: Mapped[UuidPrimaryKey]
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_membership_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    request_id: Mapped[str | None] = mapped_column(String(128))
    ip_hash: Mapped[str | None] = mapped_column(String(128))
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_VARIANT, nullable=False, default=dict
    )
    created_at: Mapped[CreatedAt]

    __table_args__ = (
        ForeignKeyConstraint(
            ["merchant_id", "actor_membership_id"],
            ["merchant_memberships.merchant_id", "merchant_memberships.id"],
            name="fk_audit_actor_same_merchant",
        ),
        Index("ix_audit_events_merchant_created", "merchant_id", "created_at"),
        Index(
            "ix_audit_events_merchant_resource",
            "merchant_id",
            "resource_type",
            "resource_id",
        ),
    )


__all__ = ["AuditEvent"]
