"""Orders, receiving accounts, and trusted merchant transaction models."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from proofpay.db.base import JSON_VARIANT, Base

from .enums import (
    OrderStatus,
    PaymentAccountStatus,
    TransactionSourceType,
    TransactionStatus,
    TransactionTrustLevel,
    enum_column,
)
from .types import CreatedAt, MoneyMinor, UpdatedAt, UuidPrimaryKey


class Order(Base):
    """A sale or delivery whose payment may be verified."""

    __tablename__ = "orders"

    id: Mapped[UuidPrimaryKey]
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    external_order_ref: Mapped[str | None] = mapped_column(String(255))
    customer_reference: Mapped[str | None] = mapped_column(String(255))
    expected_amount_minor: Mapped[MoneyMinor]
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[OrderStatus] = enum_column(OrderStatus, default=OrderStatus.PENDING_PAYMENT)
    assigned_verifier_membership_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    __table_args__ = (
        UniqueConstraint("merchant_id", "id", name="uq_order_merchant_id"),
        UniqueConstraint("merchant_id", "external_order_ref", name="uq_order_merchant_ref"),
        CheckConstraint("expected_amount_minor >= 0", name="order_amount_nonnegative"),
        ForeignKeyConstraint(
            ["merchant_id", "branch_id"],
            ["branches.merchant_id", "branches.id"],
            name="fk_order_branch_same_merchant",
        ),
        ForeignKeyConstraint(
            ["merchant_id", "assigned_verifier_membership_id"],
            ["merchant_memberships.merchant_id", "merchant_memberships.id"],
            name="fk_order_verifier_same_merchant",
        ),
        Index(
            "ix_orders_merchant_assignee_status",
            "merchant_id",
            "assigned_verifier_membership_id",
            "status",
        ),
    )


class PaymentAccount(Base):
    """A merchant receiving account without secrets or login credentials."""

    __tablename__ = "payment_accounts"

    id: Mapped[UuidPrimaryKey]
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_code: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    masked_account_ref: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[PaymentAccountStatus] = enum_column(
        PaymentAccountStatus, default=PaymentAccountStatus.ACTIVE
    )
    created_at: Mapped[CreatedAt]

    __table_args__ = (
        UniqueConstraint("merchant_id", "id", name="uq_payment_account_merchant_id"),
        Index("ix_payment_accounts_merchant_provider", "merchant_id", "provider_code"),
    )


class MerchantTransaction(Base):
    """Normalized merchant-side evidence that money was received."""

    __tablename__ = "merchant_transactions"

    id: Mapped[UuidPrimaryKey]
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    payment_account_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    provider_code: Mapped[str] = mapped_column(String(64), nullable=False)
    external_transaction_id: Mapped[str] = mapped_column(String(255), nullable=False)
    amount_minor: Mapped[MoneyMinor]
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    sender_name: Mapped[str | None] = mapped_column(String(255))
    sender_reference: Mapped[str | None] = mapped_column(String(128))
    receiver_name: Mapped[str | None] = mapped_column(String(255))
    occurred_at: Mapped[dt.datetime]
    status: Mapped[TransactionStatus] = enum_column(
        TransactionStatus, default=TransactionStatus.POSTED
    )
    source_type: Mapped[TransactionSourceType] = enum_column(
        TransactionSourceType, default=TransactionSourceType.MANUAL
    )
    trust_level: Mapped[TransactionTrustLevel] = enum_column(
        TransactionTrustLevel, default=TransactionTrustLevel.PARTIAL
    )
    source_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON_VARIANT, nullable=True)
    ingested_at: Mapped[dt.datetime]
    created_at: Mapped[CreatedAt]

    __table_args__ = (
        UniqueConstraint("merchant_id", "id", name="uq_transaction_merchant_id"),
        UniqueConstraint(
            "merchant_id",
            "provider_code",
            "payment_account_id",
            "external_transaction_id",
            name="uq_transaction_merchant_provider_external",
        ),
        ForeignKeyConstraint(
            ["merchant_id", "payment_account_id"],
            ["payment_accounts.merchant_id", "payment_accounts.id"],
            name="fk_transaction_account_same_merchant",
        ),
        Index(
            "ix_transactions_merchant_provider_occurred",
            "merchant_id",
            "provider_code",
            "occurred_at",
        ),
        Index(
            "ix_transactions_merchant_account_status_occurred",
            "merchant_id",
            "payment_account_id",
            "status",
            "occurred_at",
        ),
        CheckConstraint("amount_minor >= 0", name="transaction_amount_nonnegative"),
    )


__all__ = ["MerchantTransaction", "Order", "PaymentAccount"]
