"""Demo authentication contract and the role boundary used by the stub."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

from proofpay.api.errors import ERROR_RESPONSES

from .schemas import MembershipRole, TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"], responses=ERROR_RESPONSES)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


# ── The verifier's beat ───────────────────────────────────────────
# A VERIFIER (the rider) is assigned individual orders; every other role sees
# the merchant's whole book.  This set is the assignment.
#
# DELIBERATE: it stays at one order even now that /orders offers five.  The
# temptation when the picker landed was to widen it to all five so that "the
# picker works for everybody", but the rider seeing exactly one of five orders
# is not a gap — it is the only place in the demo where the role boundary is
# visible at all.  Widen this and GET /orders returns the same five rows for
# every role, `_assert_order_scope` in verifications.py can never fire, and the
# 403 we tell reviewers about becomes unreachable.  The frontend signs in as
# "owner" (MERCHANT_ADMIN, see `_principal_for_username`), which is neither
# REVIEWER nor VERIFIER, so it already reaches all five; nothing about the
# picker needs this widened.
DEMO_VERIFIER_ORDER_IDS: frozenset[str] = frozenset({"order_demo_1001"})


@dataclass(frozen=True, slots=True)
class DemoPrincipal:
    user_id: str
    merchant_id: str
    display_name: str
    role: MembershipRole
    scopes: tuple[str, ...]
    assigned_order_ids: frozenset[str] = DEMO_VERIFIER_ORDER_IDS


_PRINCIPALS: dict[str, DemoPrincipal] = {
    "stub-access-token": DemoPrincipal(
        user_id="user_demo_001",
        merchant_id="merchant_demo_001",
        display_name="ProofPay Demo Owner",
        role=MembershipRole.MERCHANT_ADMIN,
        scopes=("claims:submit", "claims:read", "txn:read", "txn:write", "reviews:write"),
    ),
    "stub-access-token:manager": DemoPrincipal(
        user_id="user_demo_manager",
        merchant_id="merchant_demo_001",
        display_name="ProofPay Demo Manager",
        role=MembershipRole.MANAGER,
        scopes=("claims:submit", "claims:read", "txn:read", "txn:write", "reviews:write"),
    ),
    "stub-access-token:rider": DemoPrincipal(
        user_id="user_demo_rider",
        merchant_id="merchant_demo_001",
        display_name="Ali Khan",
        role=MembershipRole.VERIFIER,
        scopes=("claims:submit", "claims:read", "orders:read"),
    ),
    "stub-access-token:reviewer": DemoPrincipal(
        user_id="user_demo_reviewer",
        merchant_id="merchant_demo_001",
        display_name="ProofPay Reviewer",
        role=MembershipRole.REVIEWER,
        scopes=("claims:read", "reviews:read", "reviews:write"),
    ),
}


# The single VERIFIER in the demo.  `stub_data` projects this principal's name
# onto the orders it is assigned to, so what the screen calls the assigned
# verifier and what the 403 boundary actually enforces cannot disagree.
DEMO_VERIFIER = _PRINCIPALS["stub-access-token:rider"]


def _principal_for_username(username: str) -> DemoPrincipal:
    normalized = username.strip().lower()
    if "rider" in normalized or "verifier" in normalized:
        return _PRINCIPALS["stub-access-token:rider"]
    if "review" in normalized:
        return _PRINCIPALS["stub-access-token:reviewer"]
    if "manager" in normalized:
        return _PRINCIPALS["stub-access-token:manager"]
    return _PRINCIPALS["stub-access-token"]


def get_current_principal(token: Annotated[str, Depends(oauth2_scheme)]) -> DemoPrincipal:
    principal = _PRINCIPALS.get(token)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


CurrentPrincipal = Annotated[DemoPrincipal, Depends(get_current_principal)]


def require_roles(*roles: MembershipRole):
    def dependency(principal: CurrentPrincipal) -> DemoPrincipal:
        if principal.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This role is not allowed to perform this action",
            )
        return principal

    return dependency


@router.post("/token", response_model=TokenResponse, summary="Get a demo access token")
def issue_demo_token(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> TokenResponse:
    principal = _principal_for_username(form.username)
    token = next(key for key, value in _PRINCIPALS.items() if value == principal)
    return TokenResponse(
        access_token=token,
        merchant_id=principal.merchant_id,
        role=principal.role,
        scopes=list(principal.scopes),
    )


@router.get("/me", response_model=UserResponse, summary="Read the demo user")
def read_demo_user(principal: CurrentPrincipal) -> UserResponse:
    return UserResponse(
        id=principal.user_id,
        merchant_id=principal.merchant_id,
        display_name=principal.display_name,
        role=principal.role,
        scopes=list(principal.scopes),
    )
