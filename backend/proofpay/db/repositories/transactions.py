"""Merchant-scoped transaction-feed queries for the decision engine."""

from __future__ import annotations

import uuid

from sqlalchemy import Select
from sqlalchemy.orm import Session

from proofpay.db.models import MerchantTransaction, TransactionStatus

from .base import as_uuid, one_or_none, scoped_select


def list_for_engine(
    session: Session,
    merchant_id: uuid.UUID,
) -> tuple[MerchantTransaction, ...]:
    """Load deterministic, non-reversed ledger inputs for one merchant."""
    statement: Select[tuple[MerchantTransaction]] = (
        scoped_select(MerchantTransaction, merchant_id)
        .where(MerchantTransaction.status != TransactionStatus.REVERSED)
        .order_by(MerchantTransaction.occurred_at.asc(), MerchantTransaction.id.asc())
    )
    return tuple(session.scalars(statement).all())


def get_for_merchant(
    session: Session,
    merchant_id: uuid.UUID,
    transaction_id: uuid.UUID | str,
) -> MerchantTransaction | None:
    """Return one ledger transaction with an explicit tenant predicate."""
    parsed_id = as_uuid(transaction_id)
    if parsed_id is None:
        return None
    return one_or_none(
        session,
        scoped_select(MerchantTransaction, merchant_id).where(
            MerchantTransaction.id == parsed_id
        ),
    )


__all__ = ["get_for_merchant", "list_for_engine"]
