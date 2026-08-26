"""Map the pure engine decision into the versioned HTTP response contract."""

from __future__ import annotations

from datetime import datetime

from proofpay.core.explain import ABSENT, explain
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


def _read_value(rendered: str | None) -> str | None:
    """One side of an evidence row, with `explain`'s em dash turned back into null.

    `core.explain` is a TEXT renderer: when a field could not be read it draws
    `ABSENT` -- an em dash -- because a terminal column has to contain something.
    That is a drawing, not a value, and forwarding it into JSON tells the client
    that the field WAS read and says "—".

    The client's own contract is explicit about the difference.
    `frontend/src/types.ts` declares `claimed_value: string | null`, and
    `src/lib/evidence.ts::displayValue` returns null only for null or blank —
    so an em dash arrives as an ordinary string and is printed verbatim, in place
    of the italic "not shown in this screenshot" the evidence list exists to show.
    A merchant then reads a dash where they should read that we could not see the
    field, which is a smaller claim than the truth and looks like a rendering bug.

    Null rather than an empty string, for the reason `adapt.ts` gives from the
    other side: "an empty string is nothing, not a value". Both sides of a row go
    through here independently — a MISSING outcome routinely has a real value on
    the ledger side and nothing on the receipt side.
    """
    if rendered is None or rendered == ABSENT:
        return None
    return rendered


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
                _read_value(rows_by_field[outcome.field].claimed)
                if outcome.field in rows_by_field
                else None
            ),
            recorded_value=(
                _read_value(rows_by_field[outcome.field].actual)
                if outcome.field in rows_by_field
                else None
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
