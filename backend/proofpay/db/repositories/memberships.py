"""Merchant-scoped membership lookups."""

from __future__ import annotations

import uuid

from sqlalchemy import Select
from sqlalchemy.orm import Session

from proofpay.db.models import MerchantMembership, MembershipStatus

from .base import one_or_none, scoped_select


def get_active_for_user(
    session: Session,
    merchant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> MerchantMembership | None:
    """Return the active membership for a user inside one merchant."""
    statement: Select[tuple[MerchantMembership]] = scoped_select(
        MerchantMembership, merchant_id
    ).where(
        MerchantMembership.user_id == user_id,
        MerchantMembership.status == MembershipStatus.ACTIVE,
    )
    return one_or_none(session, statement)


__all__ = ["get_active_for_user"]
