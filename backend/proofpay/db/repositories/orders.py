"""Merchant-scoped order queries."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from proofpay.db.models import Order

from .base import as_uuid, one_or_none, scoped_select


def get_for_merchant(
    session: Session,
    merchant_id: uuid.UUID,
    order_id: uuid.UUID | str,
) -> Order | None:
    """Return an order only when it belongs to ``merchant_id``."""
    parsed_id = as_uuid(order_id)
    if parsed_id is None:
        return None
    return one_or_none(
        session,
        scoped_select(Order, merchant_id).where(Order.id == parsed_id),
    )


__all__ = ["get_for_merchant"]
