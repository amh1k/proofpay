"""Identity, tenant, membership, and branch persistence models."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import ForeignKey, ForeignKeyConstraint, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from proofpay.db.base import Base

from .enums import (
    BranchStatus,
    MembershipRole,
    MembershipScope,
    MembershipStatus,
    MerchantStatus,
    UserStatus,
    enum_column,
)
from .types import CreatedAt, UpdatedAt, UuidPrimaryKey


class User(Base):
    """A human identity, independent of any merchant tenant."""

    __tablename__ = "users"

    id: Mapped[UuidPrimaryKey]
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[UserStatus] = enum_column(UserStatus, default=UserStatus.ACTIVE)
    last_login_at: Mapped[dt.datetime | None]
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]


class Merchant(Base):
    """An isolated ProofPay tenant."""

    __tablename__ = "merchants"

    id: Mapped[UuidPrimaryKey]
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    default_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="PKR")
    default_timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="Asia/Karachi"
    )
    status: Mapped[MerchantStatus] = enum_column(MerchantStatus, default=MerchantStatus.ACTIVE)
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]


class MerchantMembership(Base):
    """A user's role and authorization scope inside one merchant."""

    __tablename__ = "merchant_memberships"

    id: Mapped[UuidPrimaryKey]
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[MembershipRole] = enum_column(MembershipRole, default=MembershipRole.VERIFIER)
    scope_mode: Mapped[MembershipScope] = enum_column(
        MembershipScope, default=MembershipScope.ASSIGNED_RESOURCES
    )
    status: Mapped[MembershipStatus] = enum_column(
        MembershipStatus, default=MembershipStatus.INVITED
    )
    invited_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    __table_args__ = (
        UniqueConstraint("merchant_id", "id", name="uq_membership_merchant_id"),
        UniqueConstraint("merchant_id", "user_id", name="uq_membership_merchant_user"),
        ForeignKeyConstraint(
            ["merchant_id", "invited_by_membership_id"],
            ["merchant_memberships.merchant_id", "merchant_memberships.id"],
            name="fk_membership_invited_by_same_merchant",
        ),
    )


class Branch(Base):
    """An optional merchant location or operating unit."""

    __tablename__ = "branches"

    id: Mapped[UuidPrimaryKey]
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[BranchStatus] = enum_column(BranchStatus, default=BranchStatus.ACTIVE)
    created_at: Mapped[CreatedAt]

    __table_args__ = (
        UniqueConstraint("merchant_id", "id", name="uq_branch_merchant_id"),
        UniqueConstraint("merchant_id", "code", name="uq_branch_merchant_code"),
    )


class BranchMembership(Base):
    """A branch-level scope assignment for a merchant membership."""

    __tablename__ = "branch_memberships"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    membership_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    created_at: Mapped[CreatedAt]

    __table_args__ = (
        ForeignKeyConstraint(
            ["merchant_id", "branch_id"],
            ["branches.merchant_id", "branches.id"],
            name="fk_branch_membership_branch_same_merchant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["merchant_id", "membership_id"],
            ["merchant_memberships.merchant_id", "merchant_memberships.id"],
            name="fk_branch_membership_membership_same_merchant",
            ondelete="CASCADE",
        ),
        Index("ix_branch_memberships_merchant_membership", "merchant_id", "membership_id"),
    )


__all__ = ["Branch", "BranchMembership", "Merchant", "MerchantMembership", "User"]
