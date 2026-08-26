"""Merchant-scoped idempotency lookups."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from proofpay.db.models import IdempotencyRecord

from .base import one_or_none, scoped_select


def get_for_key(
    session: Session,
    merchant_id: uuid.UUID,
    key: str,
) -> IdempotencyRecord | None:
    """Return a key only within the requesting merchant tenant."""
    return one_or_none(
        session,
        scoped_select(IdempotencyRecord, merchant_id).where(
            IdempotencyRecord.idempotency_key == key
        ),
    )


__all__ = ["get_for_key"]
