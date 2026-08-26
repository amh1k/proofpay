"""Explicit demo controls kept separate from merchant production resources."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from proofpay.adapters.proof_store import reset as reset_proof_store
from proofpay.api.errors import ERROR_RESPONSES

from .auth import DemoPrincipal, require_roles
from .idempotency import reset as reset_idempotency
from .schemas import DemoResetResponse, MembershipRole

router = APIRouter(prefix="/demo", tags=["demo"], responses=ERROR_RESPONSES)
AdminPrincipal = Annotated[
    DemoPrincipal,
    Depends(require_roles(MembershipRole.MERCHANT_ADMIN)),
]


@router.post("/reset", response_model=DemoResetResponse, summary="Reset demo state")
def reset_demo(principal: AdminPrincipal) -> DemoResetResponse:
    reset_idempotency()
    # The proof store too, or the demo remembers across runs: a presenter who
    # checks the same receipt a second time would be told, correctly and
    # unhelpfully, that it is a duplicate of their own first run.
    reset_proof_store()
    return DemoResetResponse(
        status="reset",
        reset_at=datetime(2026, 8, 23, 11, 46, tzinfo=UTC),
    )
