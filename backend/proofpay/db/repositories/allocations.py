"""Merchant-scoped allocation queries."""

from __future__ import annotations

import uuid

from sqlalchemy import Select
from sqlalchemy.orm import Session

from proofpay.db.models import AllocationStatus, TransactionAllocation

from .base import scoped_select


def list_active_for_engine(
    session: Session,
    merchant_id: uuid.UUID,
) -> tuple[TransactionAllocation, ...]:
    """Load only active allocations visible to the engine for one merchant."""
    statement: Select[tuple[TransactionAllocation]] = (
        scoped_select(TransactionAllocation, merchant_id)
        .where(TransactionAllocation.status == AllocationStatus.ACTIVE)
        .order_by(TransactionAllocation.merchant_transaction_id.asc())
    )
    return tuple(session.scalars(statement).all())


__all__ = ["list_active_for_engine"]
