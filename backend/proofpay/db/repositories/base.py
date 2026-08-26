"""Shared helpers for merchant-scoped SQLAlchemy repositories."""

from __future__ import annotations

import uuid
from typing import TypeVar

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from proofpay.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


def as_uuid(value: uuid.UUID | str) -> uuid.UUID | None:
    """Parse an external identifier without turning malformed IDs into 500s."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (AttributeError, ValueError):
        return None


def scoped_select(model: type[ModelT], merchant_id: uuid.UUID) -> Select[tuple[ModelT]]:
    """Start every repository query with the tenant predicate."""
    return select(model).where(model.merchant_id == merchant_id)


def one_or_none(
    session: Session,
    statement: Select[tuple[ModelT]],
) -> ModelT | None:
    """Execute a scoped single-row query with a typed result."""
    return session.scalars(statement).one_or_none()


__all__ = ["ModelT", "as_uuid", "one_or_none", "scoped_select"]
