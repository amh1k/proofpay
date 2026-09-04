"""Merchant-scoped allocation queries."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Select
from sqlalchemy.orm import Session

from proofpay.db.models import (
    AllocationStatus,
    TransactionAllocation,
    VerificationAttempt,
    VerificationDecisionStatus,
)

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


def activate_for_attempt(
    session: Session,
    merchant_id: uuid.UUID,
    attempt_id: uuid.UUID,
    *,
    now: dt.datetime,
) -> TransactionAllocation | None:
    """Spend the transaction behind one verification, if there is one to spend.

    Called when the merchant APPROVES, never when the engine decides. Checking a
    receipt asks a question; approving commits to the answer, and only the second
    may consume a payment. Allocating at decision time meant a mis-click in the
    order picker spent the money and made the next check accuse an honest
    customer -- see the note at the decision site in
    `api/verification_service.py`.

    Returns None, quietly, for every case where there is nothing to spend: an
    unknown attempt, another merchant's attempt, a decision that was not
    VERIFIED, one the engine refused to name a transaction for, and a second
    approval of something already allocated. The caller answers 204 to all of
    them, so this must not raise for any.
    """
    attempt = session.scalars(
        scoped_select(VerificationAttempt, merchant_id).where(
            VerificationAttempt.id == attempt_id
        )
    ).one_or_none()

    if attempt is None or attempt.decision_status is not VerificationDecisionStatus.VERIFIED:
        return None
    if attempt.selected_transaction_id is None or attempt.order_id is None:
        return None

    # Idempotent, and deliberately checked on the TRANSACTION rather than on this
    # attempt: `uq_allocation_active_txn` is a partial unique index over ACTIVE
    # rows, so a second approval of any attempt naming the same transaction would
    # hit an IntegrityError rather than a tidy no-op.
    existing = session.scalars(
        scoped_select(TransactionAllocation, merchant_id).where(
            TransactionAllocation.merchant_transaction_id == attempt.selected_transaction_id,
            TransactionAllocation.status == AllocationStatus.ACTIVE,
        )
    ).first()
    if existing is not None:
        return existing

    allocation = TransactionAllocation(
        id=uuid.uuid4(),
        merchant_id=merchant_id,
        merchant_transaction_id=attempt.selected_transaction_id,
        order_id=attempt.order_id,
        verification_attempt_id=attempt.id,
        status=AllocationStatus.ACTIVE,
        allocated_at=now,
    )
    session.add(allocation)
    return allocation


__all__ = ["activate_for_attempt", "list_active_for_engine"]
