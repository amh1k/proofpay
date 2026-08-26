"""Merchant-scoped proof queries used by the verification service."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from proofpay.db.models import PaymentProof

from .base import as_uuid, one_or_none, scoped_select


def get_for_merchant(
    session: Session,
    merchant_id: uuid.UUID,
    proof_id: uuid.UUID | str,
) -> PaymentProof | None:
    """Return one proof only when it belongs to the merchant."""
    parsed_id = as_uuid(proof_id)
    if parsed_id is None:
        return None
    return one_or_none(
        session,
        scoped_select(PaymentProof, merchant_id).where(PaymentProof.id == parsed_id),
    )


def find_by_hash(
    session: Session,
    merchant_id: uuid.UUID,
    sha256_hash: str,
) -> PaymentProof | None:
    """Find a proof by its content hash within one merchant only."""
    return one_or_none(
        session,
        scoped_select(PaymentProof, merchant_id).where(
            PaymentProof.sha256_hash == sha256_hash
        ),
    )


__all__ = ["find_by_hash", "get_for_merchant"]
