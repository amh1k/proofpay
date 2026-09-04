"""Application service for submitting a payment-proof verification.

This module owns the verification use-case orchestration.  The HTTP router is
intentionally only a transport adapter: it parses multipart input, while this
service handles idempotency, storage, extraction, decisioning, persistence, and
response mapping.  Non-UUID demo identifiers continue to use the deterministic
fixture path for the frontend demo.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, timedelta
from functools import lru_cache
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from proofpay.adapters import proof_store
from proofpay.api.engine_inputs import (
    allocation_to_engine,
    as_utc,
    claim_to_engine,
    order_to_engine,
    transaction_to_engine,
)
from proofpay.api.verification_mapper import verification_result_from_decision
from proofpay.config import get_settings
from proofpay.core.compare.levels import Agreement, FieldOutcome
from proofpay.core.decide import DecisionPolicy, decide
from proofpay.core.models import Decision
from proofpay.core.models import PaymentClaim as EngineClaim
from proofpay.core.reasons import ReasonCode, Risk, Status
from proofpay.db.models import (
    EvidenceItem,
    EvidenceOutcome,
    IdempotencyRecord,
    IdempotencyState,
    PaymentProof,
    ProofRetentionStatus,
    VerificationAttempt,
    VerificationLifecycleStatus,
)
from proofpay.db.models import (
    PaymentClaim as PaymentClaimRecord,
)
from proofpay.db.repositories import (
    allocations,
    idempotency,
    memberships,
    orders,
    proof_fingerprints,
    proofs,
    transactions,
)
from proofpay.db.repositories.base import as_uuid
from proofpay.demo.clock import PINNED_ANCHOR
from proofpay.extraction.errors import ExtractionError
from proofpay.extraction.service import ExtractionService
from proofpay.storage import (
    InvalidImage,
    LocalStorage,
    StorageError,
    UnsupportedImage,
    UploadTooLarge,
    validate_image,
)

from .engine_demo import demo_case_for
from .v1.auth import DemoPrincipal
from .v1.idempotency import find_existing, request_fingerprint, store_response
from .v1.schemas import MembershipRole, VerificationResult

_FIXTURE_MANIFEST = (
    Path(__file__).resolve().parents[2] / ".." / "fixtures" / "demo" / "manifest.json"
)


@dataclass(frozen=True, slots=True)
class VerificationRequest:
    """Transport-independent inputs for one verification submission."""

    order_id: str
    content: bytes
    idempotency_key: str


@lru_cache(maxsize=1)
def _fixture_case_ids() -> dict[str, str]:
    """Index raw fixture hashes for the deterministic extractor path."""
    payload = json.loads(_FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    return {
        case["images"]["sha256"]: case["id"]
        for case in payload["cases"]
        if case.get("images", {}).get("sha256") and case.get("id")
    }


@lru_cache(maxsize=1)
def _extraction_service() -> ExtractionService:
    settings = get_settings()
    mode = "cloud" if settings.effective_receipt_extractor() == "qwen" else "offline"
    return ExtractionService(
        api_key=settings.dashscope_api_key,
        mode=mode,
        # None means "leave the adapter's pinned model alone". Passing it here is
        # what makes `PROOFPAY_QWEN_MODEL` do anything at all; it previously
        # stopped at the settings object.
        model=settings.qwen_model,
    )


@lru_cache(maxsize=1)
def _storage_service() -> LocalStorage:
    """Build the configured local proof store once per process."""
    settings = get_settings()
    if settings.storage_backend != "local":
        raise RuntimeError("The configured object-storage adapter is not available")
    return LocalStorage(settings.storage_local_path)


def _extract_claim(
    content: bytes,
    *,
    verification_id: str,
    merchant_id: str,
    proof_sha256: str | None = None,
):
    """Extract a claim while keeping fixture lookup tied to uploaded bytes.

    `proof_sha256` is stamped onto the claim so the engine can recognise these
    exact bytes if they arrive again — the whole of `PROOF_REUSED`. It is a
    parameter rather than a hash taken here because the caller has usually
    computed it already, and three independent `sha256(content)` calls in one
    request is three chances for them to stop agreeing. Defaulting to None keeps
    the function usable by callers with no history to compare against;
    `scripts/generate_api_mocks.py` is one.
    """
    settings = get_settings()
    fixture_digest = hashlib.sha256(content).hexdigest()
    digest = proof_sha256 if proof_sha256 is not None else fixture_digest
    if settings.effective_receipt_extractor() == "deterministic":
        # Fixture lookup is against the original upload bytes. The persisted
        # proof hash may instead identify the sanitized PNG stored privately.
        fixture_case_id = _fixture_case_ids().get(fixture_digest)
        if fixture_case_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "The deterministic extractor only accepts committed synthetic demo fixtures"
                ),
            )
        extractor_claim_id = fixture_case_id
    else:
        extractor_claim_id = verification_id

    try:
        extracted = _extraction_service().extract(content, claim_id=extractor_claim_id)
    except (ExtractionError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The screenshot could not be read as a payment proof",
        ) from exc

    # The current offline adapter already knows the receipt time, while the
    # legacy high-level normalizer does not yet copy it into its RawClaim bridge.
    if settings.effective_receipt_extractor() == "deterministic" and extracted.occurred_at is None:
        fixture_claim = _extraction_service().extractor.extract(content, extractor_claim_id)
        extracted = replace(extracted, occurred_at=fixture_claim.occurred_at)

    return replace(
        extracted,
        claim_id=verification_id,
        merchant_id=merchant_id,
        # `proof_id` names this submission; `proof_sha256` names the picture.
        # Only the second can be recognised across two uploads, which is the
        # whole of `PROOF_REUSED`.
        proof_id=verification_id,
        proof_sha256=digest,
    )


def _assert_order_scope(order_id: str, principal: DemoPrincipal) -> None:
    if principal.role is MembershipRole.VERIFIER and order_id not in principal.assigned_order_ids:
        raise HTTPException(status_code=403, detail="You may only verify assigned orders")


def _validated_upload(content: bytes):
    """Validate and store an upload, translating boundary failures to HTTP."""
    settings = get_settings()
    try:
        validated = validate_image(content, max_bytes=settings.max_upload_bytes)
        _storage_service().put(validated.storage_key, validated.stored_bytes)
        return validated
    except UploadTooLarge as exc:
        raise HTTPException(
            status_code=413,
            detail="Screenshot exceeds the configured upload limit",
        ) from exc
    except UnsupportedImage as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except InvalidImage as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (StorageError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="Proof storage is unavailable") from exc


def _validate_upload(content: bytes):
    """Validate bytes without writing an object (used by the DB-scoped key)."""
    settings = get_settings()
    try:
        return validate_image(content, max_bytes=settings.max_upload_bytes)
    except UploadTooLarge as exc:
        raise HTTPException(
            status_code=413,
            detail="Screenshot exceeds the configured upload limit",
        ) from exc
    except UnsupportedImage as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except InvalidImage as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _submit_demo(
    request: VerificationRequest,
    *,
    principal: DemoPrincipal,
    demo_case,
) -> VerificationResult:
    """Keep the deterministic fixture path used by the frontend demo."""
    fingerprint = request_fingerprint(request.order_id, request.content)
    existing = find_existing(principal.merchant_id, request.idempotency_key, fingerprint)
    if existing is not None:
        return existing

    validated_upload = _validated_upload(request.content)
    verification_id = f"verification_{uuid4().hex}"
    proof_sha256 = proof_store.content_sha256(request.content)
    try:
        claim = _extract_claim(
            request.content,
            verification_id=verification_id,
            merchant_id=principal.merchant_id,
            proof_sha256=proof_sha256,
        )
    except Exception:
        try:
            _storage_service().delete(validated_upload.storage_key)
        except StorageError:
            pass
        raise

    evaluated_at = PINNED_ANCHOR.astimezone(UTC)
    decision = decide(
        claim,
        demo_case.order,
        demo_case.ledger,
        demo_case.allocations,
        now=evaluated_at,
        policy=DecisionPolicy(),
        # This merchant's own accepted proofs, and nobody else's. Reading the
        # store here rather than inside the engine is the whole reason `core`
        # can stay pure: it compares hashes it was handed and never asks where
        # they came from.
        prior_proofs=proof_store.prior_proofs(principal.merchant_id),
    )
    result = verification_result_from_decision(
        decision,
        claim=claim,
        order=demo_case.order,
        ledger=demo_case.ledger,
        verification_id=verification_id,
        created_at=evaluated_at,
    )
    # A VERIFIED proof is held PENDING, not recorded. Both halves matter, and
    # `adapters/proof_store.py` carries the full argument:
    #
    #   VERIFIED, because a refused submission consumed no money — and because
    #   recording an override would let the demo's byte-identical G01/D01 pair
    #   flip order_demo_1001 to DUPLICATE depending on the presenter's click
    #   order.
    #
    #   PENDING, because checking a receipt is not accepting it. A merchant who
    #   picks the wrong order in the picker, sees VERIFIED, backs out and
    #   re-checks against the right one must not be told their honest customer
    #   reused a screenshot. Nothing here has been counted or allocated yet;
    #   `POST /verifications/{id}/approve` is where it becomes spent.
    if decision.status is Status.VERIFIED:
        proof_store.record_pending(
            principal.merchant_id,
            verification_id=verification_id,
            sha256=proof_sha256,
            order_id=demo_case.order.order_id,
            order_ref=demo_case.order.reference,
            submitted_at=evaluated_at,
        )
    store_response(principal.merchant_id, request.idempotency_key, fingerprint, result)
    return result


def _evidence_outcome(agreement: str) -> EvidenceOutcome:
    """Map an engine field direction to the persistence evidence enum."""
    return {
        "AGREE": EvidenceOutcome.PASS,
        "CONTRADICT": EvidenceOutcome.FAIL,
        "WEAK": EvidenceOutcome.WARNING,
        "MISSING": EvidenceOutcome.UNKNOWN,
    }.get(agreement, EvidenceOutcome.UNKNOWN)


def _persisted_claim(
    claim: EngineClaim,
    *,
    merchant_id: UUID,
    proof_id: UUID,
    claim_id: UUID,
) -> PaymentClaimRecord:
    occurred_at = claim.occurred_at
    return PaymentClaimRecord(
        id=claim_id,
        merchant_id=merchant_id,
        payment_proof_id=proof_id,
        provider_code=claim.provider,
        claimed_amount_minor=claim.amount.minor if claim.amount else None,
        currency=claim.amount.currency if claim.amount else None,
        sender_name=claim.sender_name,
        receiver_name=claim.receiver_name,
        external_transaction_id=claim.reference_id,
        claimed_occurred_at=occurred_at.resolved_utc if occurred_at else None,
        timestamp_raw=None,
        timezone_assumption=occurred_at.assumed_tz if occurred_at else None,
        field_confidences=dict(claim.field_confidences),
        raw_ocr_text=None,
        provider_template=None,
        parser_version=claim.parser_version,
    )


def _stored_decision(
    attempt: VerificationAttempt,
    evidence_rows: tuple[EvidenceItem, ...],
) -> Decision:
    """Rebuild the immutable decision shell needed to render a stored result."""
    agreement_by_outcome = {
        EvidenceOutcome.PASS: Agreement.AGREE,
        EvidenceOutcome.FAIL: Agreement.CONTRADICT,
        EvidenceOutcome.WARNING: Agreement.WEAK,
        EvidenceOutcome.UNKNOWN: Agreement.MISSING,
    }
    evidence = tuple(
        FieldOutcome(
            field=(row.details or {}).get("field", row.evidence_code),
            level_code=row.evidence_code,
            label=row.evidence_code,
            score=float(row.score or 0),
            agreement=agreement_by_outcome[row.outcome],
            detail={k: v for k, v in (row.details or {}).items() if k != "field"},
        )
        for row in evidence_rows
    )
    try:
        reason = ReasonCode(attempt.summary_reason_code) if attempt.summary_reason_code else None
    except ValueError:
        reason = None
    return Decision(
        status=attempt.decision_status or Status.NEEDS_REVIEW,
        risk=attempt.risk_level or Risk.MEDIUM,
        confidence=float(attempt.decision_confidence or 0),
        reasons=(reason,) if reason else (),
        matched_txn_id=(
            str(attempt.selected_transaction_id) if attempt.selected_transaction_id else None
        ),
        fired_rule_id="PERSISTED",
        evidence=evidence,
        observations=(),
        ruleset_version=attempt.rule_set_version or "unknown",
        policy_fingerprint="persisted",
        engine_version=(evidence_rows[0].component_version if evidence_rows else "unknown"),
        evaluated_at=as_utc(attempt.decided_at or attempt.created_at) or PINNED_ANCHOR,
    )


def _stored_result(
    session: Session,
    *,
    merchant_id: UUID,
    attempt: VerificationAttempt,
) -> VerificationResult | None:
    """Render one merchant-scoped persisted attempt without re-running rules."""
    if (
        attempt.order_id is None
        or attempt.payment_claim_id is None
        or attempt.decision_status is None
    ):
        return None
    order_record = orders.get_for_merchant(session, merchant_id, attempt.order_id)
    claim_record = session.scalars(
        select(PaymentClaimRecord).where(
            PaymentClaimRecord.merchant_id == merchant_id,
            PaymentClaimRecord.id == attempt.payment_claim_id,
        )
    ).one_or_none()
    if order_record is None or claim_record is None:
        return None
    evidence_rows = tuple(
        session.scalars(
            select(EvidenceItem)
            .where(
                EvidenceItem.merchant_id == merchant_id,
                EvidenceItem.verification_attempt_id == attempt.id,
        )
        .order_by(EvidenceItem.id.asc())
        ).all()
    )
    ledger = tuple(
        transaction_to_engine(record)
        for record in transactions.list_for_engine(session, merchant_id)
    )
    claim = claim_to_engine(claim_record)
    order = order_to_engine(order_record)
    decision = _stored_decision(attempt, evidence_rows)
    return verification_result_from_decision(
        decision,
        claim=claim,
        order=order,
        ledger=ledger,
        verification_id=str(attempt.id),
        created_at=attempt.created_at,
    )


def _submit_persisted(
    request: VerificationRequest,
    *,
    principal: DemoPrincipal,
    session: Session,
    merchant_id: UUID,
    user_id: UUID,
    order_id: UUID,
) -> VerificationResult:
    """Run the real merchant-scoped flow and commit its audit trail atomically."""
    fingerprint = request_fingerprint(request.order_id, request.content)
    prior_idempotency = idempotency.get_for_key(
        session, merchant_id, request.idempotency_key
    )
    if prior_idempotency is not None:
        if prior_idempotency.request_fingerprint != fingerprint:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="IDEMPOTENCY_CONFLICT: the key was used with a different request",
            )
        if (
            prior_idempotency.state is IdempotencyState.COMPLETED
            and prior_idempotency.response_body
        ):
            replay = VerificationResult.model_validate(prior_idempotency.response_body)
            session.rollback()
            return replay
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The same verification request is already being processed",
        )
    session.rollback()

    membership = memberships.get_active_for_user(session, merchant_id, user_id)
    order_record = orders.get_for_merchant(session, merchant_id, order_id)
    if membership is None:
        session.rollback()
        raise HTTPException(status_code=403, detail="Active merchant membership required")
    if order_record is None:
        session.rollback()
        raise HTTPException(status_code=404, detail="Order not found")
    if (
        str(principal.role) == "VERIFIER"
        and order_record.assigned_verifier_membership_id not in {None, membership.id}
    ):
        session.rollback()
        raise HTTPException(status_code=403, detail="You may only verify assigned orders")
    session.rollback()

    validated_upload = _validate_upload(request.content)
    # DB uniqueness is merchant-scoped; the object key must be scoped too.
    candidate_storage_key = (
        f"proofs/{merchant_id}/{validated_upload.stored_sha256[:2]}"
        f"/{validated_upload.stored_sha256}.png"
    )
    existing_proof = proofs.find_by_hash(session, merchant_id, validated_upload.stored_sha256)
    existing_storage_key = existing_proof.storage_key if existing_proof else None
    session.rollback()
    storage_key = existing_storage_key or candidate_storage_key
    if existing_proof is None:
        try:
            _storage_service().put(storage_key, validated_upload.stored_bytes)
        except (StorageError, RuntimeError) as exc:
            raise HTTPException(status_code=503, detail="Proof storage is unavailable") from exc

    attempt_id = uuid4()
    proof_created = False
    try:
        try:
            claim = _extract_claim(
                request.content,
                verification_id=str(attempt_id),
                merchant_id=str(merchant_id),
                # The hash of the STORED bytes, matching what
                # `proofs.find_by_hash` indexes above, so the claim and the
                # `payment_proofs` row name the same picture.
                proof_sha256=validated_upload.stored_sha256,
            )
        except Exception:
            if existing_proof is None:
                try:
                    _storage_service().delete(storage_key)
                except StorageError:
                    pass
            raise
        claim = replace(claim, proof_id=str(attempt_id))

        evaluated_at = PINNED_ANCHOR.astimezone(UTC)
        with session.begin():
            membership = memberships.get_active_for_user(session, merchant_id, user_id)
            order_record = orders.get_for_merchant(session, merchant_id, order_id)
            if membership is None or order_record is None:
                raise HTTPException(status_code=404, detail="Order or membership not found")

            proof_record = proofs.find_by_hash(
                session, merchant_id, validated_upload.stored_sha256
            )
            if proof_record is None:
                proof_created = True
                proof_record = PaymentProof(
                    id=uuid4(),
                    merchant_id=merchant_id,
                    uploaded_by_membership_id=membership.id,
                    storage_key=storage_key,
                    media_type=validated_upload.stored_media_type,
                    byte_size=validated_upload.stored_size,
                    width_px=validated_upload.width,
                    height_px=validated_upload.height,
                    sha256_hash=validated_upload.stored_sha256,
                    retention_status=ProofRetentionStatus.ACTIVE,
                )
                session.add(proof_record)
                session.flush()

            claim_record = _persisted_claim(
                claim,
                merchant_id=merchant_id,
                proof_id=proof_record.id,
                claim_id=uuid4(),
            )
            session.add(claim_record)
            attempt_record = VerificationAttempt(
                id=attempt_id,
                merchant_id=merchant_id,
                order_id=order_id,
                payment_proof_id=proof_record.id,
                payment_claim_id=claim_record.id,
                requested_by_membership_id=membership.id,
                lifecycle_status=VerificationLifecycleStatus.PROCESSING,
                started_at=evaluated_at,
            )
            session.add(attempt_record)

            order = order_to_engine(order_record)
            ledger_records = transactions.list_for_engine(session, merchant_id)
            allocation_records = allocations.list_active_for_engine(session, merchant_id)
            ledger = tuple(transaction_to_engine(record) for record in ledger_records)
            active_allocations = tuple(
                allocation_to_engine(record) for record in allocation_records
            )
            # Only proofs with an active allocation are accepted history. A
            # merely uploaded proof has consumed nothing and must not trigger
            # R025 on a later submission.
            decision = decide(
                claim,
                order,
                ledger,
                active_allocations,
                now=evaluated_at,
                policy=DecisionPolicy(),
                prior_proofs=proof_fingerprints.list_accepted_for_engine(
                    session, merchant_id
                ),
            )

            attempt_record.lifecycle_status = VerificationLifecycleStatus.DECIDED
            attempt_record.decision_status = decision.status
            attempt_record.risk_level = decision.risk
            attempt_record.decision_confidence = decision.confidence
            attempt_record.selected_transaction_id = (
                as_uuid(decision.matched_txn_id) if decision.matched_txn_id else None
            )
            attempt_record.rule_set_version = decision.ruleset_version
            attempt_record.summary_reason_code = (
                decision.reasons[0].value if decision.reasons else None
            )
            attempt_record.decided_at = decision.evaluated_at

            # Persist the attempt row before inserting children that refer to
            # it through composite foreign keys.
            session.flush()

            for outcome in decision.evidence:
                session.add(
                    EvidenceItem(
                        id=uuid4(),
                        merchant_id=merchant_id,
                        verification_attempt_id=attempt_id,
                        evidence_code=outcome.level_code,
                        outcome=_evidence_outcome(outcome.agreement.value),
                        observed_value=None,
                        expected_value=None,
                        score=outcome.score,
                        details={"field": outcome.field, **dict(outcome.detail)},
                        source_component="decision_engine",
                        component_version=decision.engine_version,
                    )
                )

            # NO ALLOCATION IS WRITTEN HERE, and that is the point.
            #
            # A VERIFIED decision used to allocate the transaction immediately,
            # which meant that merely LOOKING at a receipt spent the money behind
            # it. Reproduced end to end: a shop with two open orders of the same
            # value -- the ordinary case for a single-product seller -- picks the
            # wrong one in the order picker, sees VERIFIED, backs out without
            # approving, and re-checks the same receipt against the right order.
            # The second check answered DUPLICATE / R020 / TXN_ALREADY_ALLOCATED
            # and told the merchant to refuse an honest customer, on the strength
            # of their own mis-click. Nothing had been approved.
            #
            # `adapters/proof_store.py` already carries this rule for the demo
            # path and states it plainly: a proof is spent when the decision was
            # VERIFIED *and the merchant then approved*. Both, not either. This
            # path had the first half only.
            #
            # So the allocation is created by `POST /verifications/{id}/approve`,
            # which is where the merchant actually commits. The attempt row keeps
            # everything that needs -- `selected_transaction_id`, `order_id` and
            # `decision_status` are all persisted above.
            #
            # This also gates R025 for free: `proof_fingerprints` finds accepted
            # proofs by joining ACTIVE allocations, so an unapproved check now
            # leaves no proof history either. One rule, both duplicate signals.

            # The allocation and attempt use composite foreign keys without
            # ORM relationships. Flush them before the idempotency lookup can
            # trigger an autoflush, so SQLite and PostgreSQL validate the
            # complete graph in the intended order.
            session.flush()

            result = verification_result_from_decision(
                decision,
                claim=claim,
                order=order,
                ledger=ledger,
                verification_id=str(attempt_id),
                created_at=evaluated_at,
            )
            idempotency_record = idempotency.get_for_key(
                session, merchant_id, request.idempotency_key
            )
            if idempotency_record is None:
                idempotency_record = IdempotencyRecord(
                    id=uuid4(),
                    merchant_id=merchant_id,
                    idempotency_key=request.idempotency_key,
                    request_fingerprint=fingerprint,
                    verification_attempt_id=attempt_id,
                    state=IdempotencyState.COMPLETED,
                    response_status=status.HTTP_201_CREATED,
                    response_body=result.model_dump(mode="json"),
                    expires_at=evaluated_at + timedelta(days=1),
                )
                session.add(idempotency_record)
            else:
                idempotency_record.verification_attempt_id = attempt_id
                idempotency_record.state = IdempotencyState.COMPLETED
                idempotency_record.response_status = status.HTTP_201_CREATED
                idempotency_record.response_body = result.model_dump(mode="json")
            session.flush()
    except Exception:
        # The database transaction rolls back. Remove only the merchant-scoped
        # object created for this request; a pre-existing proof remains intact.
        if proof_created:
            try:
                _storage_service().delete(storage_key)
            except StorageError:
                pass
        raise

    return result


def submit_verification(
    request: VerificationRequest,
    *,
    principal: DemoPrincipal,
    session: Session | None = None,
) -> VerificationResult:
    """Run the demo or merchant-scoped verification use case."""
    merchant_id = as_uuid(principal.merchant_id)
    user_id = as_uuid(principal.user_id)
    order_id = as_uuid(request.order_id)
    if session is not None and merchant_id and user_id and order_id:
        return _submit_persisted(
            request,
            principal=principal,
            session=session,
            merchant_id=merchant_id,
            user_id=user_id,
            order_id=order_id,
        )
    _assert_order_scope(request.order_id, principal)
    demo_case = demo_case_for(request.order_id, principal.merchant_id)
    return _submit_demo(request, principal=principal, demo_case=demo_case)


__all__ = ["VerificationRequest", "submit_verification"]
