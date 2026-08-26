"""Merchant-scoped verification-attempt queries."""

from __future__ import annotations

import uuid

from sqlalchemy import Select
from sqlalchemy.orm import Session

from proofpay.db.models import VerificationAttempt

from .base import as_uuid, one_or_none, scoped_select


def get_for_merchant(
    session: Session,
    merchant_id: uuid.UUID,
    attempt_id: uuid.UUID | str,
) -> VerificationAttempt | None:
    """Return one verification attempt with an explicit tenant predicate."""
    parsed_id = as_uuid(attempt_id)
    if parsed_id is None:
        return None
    return one_or_none(
        session,
        scoped_select(VerificationAttempt, merchant_id).where(
            VerificationAttempt.id == parsed_id
        ),
    )


def list_for_merchant(
    session: Session,
    merchant_id: uuid.UUID,
    *,
    limit: int = 50,
) -> tuple[VerificationAttempt, ...]:
    """List recent attempts within one merchant, bounded for API use."""
    if limit < 1:
        raise ValueError("limit must be positive")
    statement: Select[tuple[VerificationAttempt]] = (
        scoped_select(VerificationAttempt, merchant_id)
        .order_by(VerificationAttempt.created_at.desc(), VerificationAttempt.id.desc())
        .limit(limit)
    )
    return tuple(session.scalars(statement).all())


__all__ = ["get_for_merchant", "list_for_merchant"]
