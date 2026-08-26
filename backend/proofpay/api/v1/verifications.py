"""Verification routes connecting uploads to the real decision engine."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile, status

from proofpay.api.errors import ERROR_RESPONSES
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

from ..engine_demo import demo_case_for
from .auth import CurrentPrincipal, DemoPrincipal, require_roles
from .idempotency import find_existing, request_fingerprint, store_response
from .schemas import (
    MembershipRole,
    VerificationHistory,
    VerificationListItem,
    VerificationResult,
    VerificationStatus,
)
from .stub_data import STUB_HISTORY, verification_by_id

router = APIRouter(prefix="/verifications", tags=["verifications"], responses=ERROR_RESPONSES)
_ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp"}
_FIXTURE_MANIFEST = Path(__file__).resolve().parents[4] / "fixtures" / "demo" / "manifest.json"
SubmitPrincipal = Annotated[
    DemoPrincipal,
    Depends(
        require_roles(
            MembershipRole.MERCHANT_ADMIN,
            MembershipRole.MANAGER,
            MembershipRole.VERIFIER,
        )
    ),
]


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
    """Extract a claim while keeping fixture lookup tied to the uploaded bytes."""
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
    # legacy high-level normalizer does not yet copy that field into its
    # RawClaim bridge. Recover it from the same deterministic extractor until
    # the extraction track updates that bridge; a missing time can otherwise
    # incorrectly downgrade an otherwise exact match to review.
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


def _can_view(result: VerificationResult, principal: DemoPrincipal) -> bool:
    if principal.role is MembershipRole.VERIFIER:
        return result.order_id in principal.assigned_order_ids
    if principal.role is MembershipRole.REVIEWER:
        return result.id == "verification_demo_1004"
    return True


def _history_item_visible(item: VerificationListItem, principal: DemoPrincipal) -> bool:
    if principal.role is MembershipRole.VERIFIER:
        return item.order_id in principal.assigned_order_ids
    if principal.role is MembershipRole.REVIEWER:
        return item.id == "verification_demo_1004"
    return True


async def _submit_verification(
    order_id: Annotated[str, Form(...)],
    screenshot: Annotated[UploadFile, File(...)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    principal: SubmitPrincipal,
    client_resized: Annotated[str | None, Header(alias="X-Client-Resized")] = None,
) -> VerificationResult:
    """Run extraction and the real decision engine for one demo verification."""
    _assert_order_scope(order_id, principal)
    demo_case = demo_case_for(order_id, principal.merchant_id)
    if screenshot.content_type not in _ALLOWED_MEDIA_TYPES:
        raise HTTPException(status_code=415, detail="Only JPEG, PNG, and WebP images are accepted")

    content = await screenshot.read()

    fingerprint = request_fingerprint(order_id, content)
    existing = find_existing(principal.merchant_id, idempotency_key, fingerprint)
    if existing is not None:
        return existing

    settings = get_settings()
    try:
        # This verifies the actual bytes and creates the private, metadata-free
        # PNG that should be retained.  The original bytes remain the input to
        # the deterministic fixture extractor, whose manifest is keyed by the
        # original upload hash.
        validated_upload = validate_image(content, max_bytes=settings.max_upload_bytes)
        _storage_service().put(
            validated_upload.storage_key,
            validated_upload.stored_bytes,
        )
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
            content,
            verification_id=verification_id,
            merchant_id=principal.merchant_id,
        )
    except Exception:
        # There is no database row to reconcile yet.  Do not leave an object
        # behind when extraction rejects the upload; the persistence slice will
        # replace this with a durable proof-retention state.
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
    store_response(principal.merchant_id, idempotency_key, fingerprint, result)
    return result


router.add_api_route(
    "",
    _submit_verification,
    methods=["POST"],
    response_model=VerificationResult,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a payment proof",
    description=(
        "Accepts a multipart screenshot and an Idempotency-Key. "
        "The screenshot is extracted and evaluated by the versioned decision engine."
    ),
)


@router.get("", response_model=VerificationHistory, summary="List verification history")
def list_verifications(
    principal: CurrentPrincipal,
    status: Annotated[VerificationStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> VerificationHistory:
    visible_items = [item for item in STUB_HISTORY.items if _history_item_visible(item, principal)]
    items = [item for item in visible_items if status is None or item.status is status]
    return VerificationHistory(items=items[:limit], total=len(items))


@router.get("/{verification_id}", response_model=VerificationResult, summary="Read a verification")
def get_verification(verification_id: str, principal: CurrentPrincipal) -> VerificationResult:
    result = verification_by_id(verification_id)
    if result is None or not _can_view(result, principal):
        raise HTTPException(status_code=404, detail="Verification not found")
    return result


claims_router = APIRouter(prefix="/claims", tags=["claims"], responses=ERROR_RESPONSES)


async def create_claim_alias(
    order_id: Annotated[str, Form(...)],
    screenshot: Annotated[UploadFile, File(...)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    principal: SubmitPrincipal,
    client_resized: Annotated[str | None, Header(alias="X-Client-Resized")] = None,
) -> VerificationResult:
    return await _submit_verification(
        order_id,
        screenshot,
        idempotency_key,
        principal,
        client_resized,
    )


claims_router.add_api_route(
    "",
    create_claim_alias,
    methods=["POST"],
    response_model=VerificationResult,
    status_code=201,
    deprecated=True,
    summary="Submit a payment claim (legacy alias)",
)
