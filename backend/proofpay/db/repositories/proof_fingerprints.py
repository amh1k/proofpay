"""Accepted proof fingerprints for the decision engine."""

from __future__ import annotations

import uuid

from sqlalchemy import Select
from sqlalchemy.orm import Session

from proofpay.core.models import ProofFingerprint
from proofpay.db.models import (
    AllocationStatus,
    Order,
    PaymentProof,
    TransactionAllocation,
    VerificationAttempt,
    VerificationDecisionStatus,
)

from .base import scoped_select


def list_accepted_for_engine(
    session: Session,
    merchant_id: uuid.UUID,
) -> tuple[ProofFingerprint, ...]:
    """Return only proofs attached to an active allocation in this merchant."""
    statement: Select[tuple[str, uuid.UUID, str | None, uuid.UUID | None, object | None]] = (
        scoped_select(PaymentProof, merchant_id)
        .join(
            VerificationAttempt,
            (VerificationAttempt.merchant_id == PaymentProof.merchant_id)
            & (VerificationAttempt.payment_proof_id == PaymentProof.id),
        )
        .join(
            TransactionAllocation,
            (TransactionAllocation.merchant_id == VerificationAttempt.merchant_id)
            & (TransactionAllocation.verification_attempt_id == VerificationAttempt.id),
        )
        .join(
            Order,
            (Order.merchant_id == VerificationAttempt.merchant_id)
            & (Order.id == VerificationAttempt.order_id),
        )
        .where(
            VerificationAttempt.decision_status == VerificationDecisionStatus.VERIFIED,
            TransactionAllocation.status == AllocationStatus.ACTIVE,
        )
        .with_only_columns(
            PaymentProof.sha256_hash,
            Order.id,
            Order.external_order_ref,
            VerificationAttempt.id,
            VerificationAttempt.decided_at,
        )
        .order_by(PaymentProof.sha256_hash.asc(), VerificationAttempt.id.asc())
    )
    rows = session.execute(statement).all()
    seen: set[str] = set()
    result: list[ProofFingerprint] = []
    for sha256, order_id, order_ref, verification_id, submitted_at in rows:
        if sha256 in seen:
            continue
        seen.add(sha256)
        result.append(
            ProofFingerprint(
                sha256=sha256,
                order_id=str(order_id) if order_id else None,
                order_ref=order_ref,
                verification_id=str(verification_id) if verification_id else None,
                submitted_at=submitted_at,
            )
        )
    return tuple(result)


__all__ = ["list_accepted_for_engine"]
