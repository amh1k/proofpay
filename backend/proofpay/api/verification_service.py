"""Application service for submitting a payment-proof verification.

This module owns the verification use-case orchestration.  The HTTP router is
intentionally only a transport adapter: it parses multipart input, while this
service handles idempotency, storage, extraction, decisioning, and response
mapping.  The current service still reads the demo order/ledger case; the next
step replaces that adapter with merchant-scoped repositories.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, status

from proofpay.api.verification_mapper import verification_result_from_decision
from proofpay.config import get_settings
from proofpay.core.decide import DecisionPolicy, decide
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
    return ExtractionService(api_key=settings.dashscope_api_key, mode=mode)


@lru_cache(maxsize=1)
def _storage_service() -> LocalStorage:
    """Build the configured local proof store once per process."""
    settings = get_settings()
    if settings.storage_backend != "local":
        raise RuntimeError("The configured object-storage adapter is not available")
    return LocalStorage(settings.storage_local_path)


def _extract_claim(content: bytes, *, verification_id: str, merchant_id: str):
    """Extract a claim while keeping fixture lookup tied to uploaded bytes."""
    settings = get_settings()
    if settings.effective_receipt_extractor() == "deterministic":
        fixture_case_id = _fixture_case_ids().get(hashlib.sha256(content).hexdigest())
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
        proof_id=verification_id,
    )


def _assert_order_scope(order_id: str, principal: DemoPrincipal) -> None:
    if principal.role is MembershipRole.VERIFIER and order_id not in principal.assigned_order_ids:
        raise HTTPException(status_code=403, detail="You may only verify assigned orders")


def submit_verification(
    request: VerificationRequest,
    *,
    principal: DemoPrincipal,
) -> VerificationResult:
    """Run the current verification use case and return its API projection."""
    _assert_order_scope(request.order_id, principal)
    demo_case = demo_case_for(request.order_id, principal.merchant_id)

    fingerprint = request_fingerprint(request.order_id, request.content)
    existing = find_existing(principal.merchant_id, request.idempotency_key, fingerprint)
    if existing is not None:
        return existing

    settings = get_settings()
    try:
        # Validate the actual image bytes and retain the sanitized PNG.  The
        # original bytes remain the input to the deterministic fixture extractor.
        validated_upload = validate_image(request.content, max_bytes=settings.max_upload_bytes)
        _storage_service().put(validated_upload.storage_key, validated_upload.stored_bytes)
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

    verification_id = f"verification_{uuid4().hex}"
    try:
        claim = _extract_claim(
            request.content,
            verification_id=verification_id,
            merchant_id=principal.merchant_id,
        )
    except Exception:
        # There is no database row to reconcile yet.  Do not leave an object
        # behind when extraction rejects the upload; persistence will replace
        # this with a durable proof-retention state.
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
    )
    result = verification_result_from_decision(
        decision,
        claim=claim,
        order=demo_case.order,
        ledger=demo_case.ledger,
        verification_id=verification_id,
        created_at=evaluated_at,
    )
    store_response(principal.merchant_id, request.idempotency_key, fingerprint, result)
    return result


__all__ = ["VerificationRequest", "submit_verification"]
