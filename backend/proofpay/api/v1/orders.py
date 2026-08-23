"""Order contract routes backed by deterministic examples."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from proofpay.api.errors import ERROR_RESPONSES

from .auth import CurrentPrincipal
from .schemas import MembershipRole, OrderList, OrderView
from .stub_data import STUB_ORDERS

router = APIRouter(prefix="/orders", tags=["orders"], responses=ERROR_RESPONSES)


@router.get("", response_model=OrderList, summary="List orders")
def list_orders(principal: CurrentPrincipal) -> OrderList:
    items = [
        order
        for order in STUB_ORDERS
        if principal.role is not MembershipRole.REVIEWER
        and (
            principal.role is not MembershipRole.VERIFIER
            or order.id in principal.assigned_order_ids
        )
    ]
    return OrderList(items=items, total=len(items))


@router.get("/{order_id}", response_model=OrderView, summary="Read an order")
def get_order(order_id: str, principal: CurrentPrincipal) -> OrderView:
    order = next((item for item in STUB_ORDERS if item.id == order_id), None)
    if (
        order is None
        or principal.role is MembershipRole.REVIEWER
        or (
            principal.role is MembershipRole.VERIFIER
            and order.id not in principal.assigned_order_ids
        )
    ):
        raise HTTPException(status_code=404, detail="Order not found")
    return order
