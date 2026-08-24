"""Map the pure engine decision into the versioned HTTP response contract."""

from __future__ import annotations

from datetime import datetime

from proofpay.core.explain import explain
from proofpay.core.models import Decision, LedgerTxn, Order, PaymentClaim

from .v1.schemas import (
    EvidenceItem,
    MatchedTransactionSummary,
    PaymentClaimView,
    VerificationResult,
    VerificationStage,
)

__all__ = ["verification_result_from_decision"]


def _mask_reference(reference: str | None) -> str | None:
    if not reference:
        return None
    if len(reference) <= 4:
        return "••••"
    return f"{reference[:2]}••••{reference[-2:]}"


def _claim_view(claim: PaymentClaim) -> PaymentClaimView:
    return PaymentClaimView(
        proof_id=claim.proof_id or claim.claim_id,
        provider=claim.provider,
        amount_minor=claim.amount.minor if claim.amount else None,
        currency=claim.amount.currency if claim.amount else "PKR",
        sender_name=claim.sender_name,
        receiver_name=claim.receiver_name,
        reference_id=claim.reference_id,
        occurred_at=claim.occurred_at.resolved_utc if claim.occurred_at else None,
    )


def _matched_view(txn: LedgerTxn | None) -> MatchedTransactionSummary | None:
    if txn is None:
        return None
    return MatchedTransactionSummary(
        id=txn.txn_id,
        provider=txn.provider or "unknown",
        masked_reference=_mask_reference(txn.reference_id),
        amount_minor=txn.amount.minor,
        currency=txn.amount.currency,
        occurred_at=txn.occurred_at,
        status="POSTED",
    )


def verification_result_from_decision(
    decision: Decision,
    *,
    claim: PaymentClaim,
    order: Order,
    ledger: tuple[LedgerTxn, ...],
    verification_id: str,
    created_at: datetime,
) -> VerificationResult:
    """Build an API response without re-deciding or inventing evidence."""
    matched = next(
        (txn for txn in ledger if txn.txn_id == decision.matched_txn_id),
        None,
    )
    explanation = explain(decision, claim=claim, txn=matched, order=order)
    rows_by_field = {row.field: row for row in explanation.rows}

    evidence = [
        EvidenceItem(
            field=outcome.field,
            level_code=outcome.level_code,
            label=outcome.label,
            score=outcome.score,
            agreement=outcome.agreement,
            claimed_value=(
                rows_by_field[outcome.field].claimed if outcome.field in rows_by_field else None
            ),
            recorded_value=(
                rows_by_field[outcome.field].actual if outcome.field in rows_by_field else None
            ),
            detail=dict(outcome.detail),
        )
        for outcome in decision.evidence
    ]

    return VerificationResult(
        id=verification_id,
        order_id=order.order_id,
        status=decision.status,
        stage=VerificationStage.COMPLETE,
        risk=decision.risk,
        confidence=decision.confidence,
        claim=_claim_view(claim),
        matched_transaction=_matched_view(matched),
        matched_txn_id=decision.matched_txn_id,
        reasons=list(decision.reasons),
        summary=explanation.summary,
        fired_rule_id=decision.fired_rule_id,
        evidence=evidence,
        observations=list(decision.observations),
        recommended_action=explanation.recommended_action,
        ruleset_version=decision.ruleset_version,
        policy_fingerprint=decision.policy_fingerprint,
        engine_version=decision.engine_version,
        evaluated_at=decision.evaluated_at,
        created_at=created_at,
        degraded=any(note.startswith("degraded:") for note in claim.notes),
    )
