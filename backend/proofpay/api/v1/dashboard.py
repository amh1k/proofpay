"""Dashboard contract route backed by deterministic examples."""

from typing import Annotated

from fastapi import APIRouter, Depends

from proofpay.api.errors import ERROR_RESPONSES

from .auth import DemoPrincipal, require_roles
from .schemas import DashboardSummary, MembershipRole
from .stub_data import STUB_DASHBOARD

router = APIRouter(prefix="/dashboard", tags=["dashboard"], responses=ERROR_RESPONSES)
AdminOrManager = Annotated[
    DemoPrincipal,
    Depends(require_roles(MembershipRole.MERCHANT_ADMIN, MembershipRole.MANAGER)),
]


@router.get("/summary", response_model=DashboardSummary, summary="Read dashboard summary")
def dashboard_summary(principal: AdminOrManager) -> DashboardSummary:
    return STUB_DASHBOARD
