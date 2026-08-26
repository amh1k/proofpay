"""Verification routes connecting uploads to the real decision engine."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile, status

from proofpay.api.errors import ERROR_RESPONSES

from ..verification_service import (
    VerificationRequest,
    _extract_claim as _extract_claim,
    submit_verification,
)
from .auth import CurrentPrincipal, DemoPrincipal, require_roles
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
    """Parse one multipart request and delegate the use case to the service."""
    if screenshot.content_type not in _ALLOWED_MEDIA_TYPES:
        raise HTTPException(status_code=415, detail="Only JPEG, PNG, and WebP images are accepted")

    content = await screenshot.read()
    return submit_verification(
        VerificationRequest(
            order_id=order_id,
            content=content,
            idempotency_key=idempotency_key,
        ),
        principal=principal,
    )


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
