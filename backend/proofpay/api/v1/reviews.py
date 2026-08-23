"""Manual review contract for ambiguous or degraded verification attempts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from proofpay.api.errors import ERROR_RESPONSES

from .auth import DemoPrincipal, require_roles
from .schemas import (
    ManualReviewView,
    MembershipRole,
    ReviewAssignmentView,
    ReviewQueue,
    ReviewRequest,
)
from .stub_data import verification_by_id

router = APIRouter(prefix="/reviews", tags=["reviews"], responses=ERROR_RESPONSES)
verification_router = APIRouter(
    prefix="/verifications", tags=["reviews"], responses=ERROR_RESPONSES
)
ReviewPrincipal = Annotated[
    DemoPrincipal,
    Depends(
        require_roles(
            MembershipRole.MERCHANT_ADMIN,
            MembershipRole.MANAGER,
            MembershipRole.REVIEWER,
        )
    ),
]

_ASSIGNMENTS = [
    ReviewAssignmentView(
        id="review_assignment_demo_1001",
        verification_id="verification_demo_1004",
        status="OPEN",
        assigned_to_role=MembershipRole.REVIEWER,
        created_at=datetime(2026, 8, 23, 11, 44, tzinfo=UTC),
    )
]


@router.get("", response_model=ReviewQueue, summary="List manual review assignments")
def list_reviews(principal: ReviewPrincipal) -> ReviewQueue:
    return ReviewQueue(items=_ASSIGNMENTS, total=len(_ASSIGNMENTS))


@verification_router.post(
    "/{verification_id}/reviews",
    response_model=ManualReviewView,
    status_code=201,
    summary="Submit a manual review outcome",
)
def submit_review(
    verification_id: str,
    payload: ReviewRequest,
    principal: ReviewPrincipal,
) -> ManualReviewView:
    if principal.role is MembershipRole.REVIEWER and verification_id != "verification_demo_1004":
        raise HTTPException(status_code=404, detail="Review assignment not found")
    verification = verification_by_id(verification_id)
    if verification is None:
        raise HTTPException(status_code=404, detail="Verification not found")

    return ManualReviewView(
        id=f"manual_review_{verification_id}",
        verification_id=verification_id,
        previous_decision_status=verification.status,
        review_outcome=payload.review_outcome,
        new_decision_status=payload.new_decision_status,
        reason_code=payload.reason_code,
        notes=payload.notes,
        created_at=datetime(2026, 8, 23, 11, 45, tzinfo=UTC),
    )
