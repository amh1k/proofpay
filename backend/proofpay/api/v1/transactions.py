"""Merchant transaction contract routes backed by deterministic examples."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from proofpay.api.errors import ERROR_RESPONSES

from .auth import DemoPrincipal, require_roles
from .schemas import MembershipRole, TransactionCreateRequest, TransactionList, TransactionView
from .stub_data import DEMO_TRANSACTION, STUB_TRANSACTIONS

router = APIRouter(prefix="/transactions", tags=["transactions"], responses=ERROR_RESPONSES)
AdminOrManager = Annotated[
    DemoPrincipal,
    Depends(require_roles(MembershipRole.MERCHANT_ADMIN, MembershipRole.MANAGER)),
]


@router.get("", response_model=TransactionList, summary="List merchant transactions")
def list_transactions(
    principal: AdminOrManager,
    provider: str | None = Query(default=None),
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> TransactionList:
    items = [item for item in STUB_TRANSACTIONS if provider is None or item.provider == provider]
    return TransactionList(items=items[:limit], total=len(items))


@router.post("", response_model=TransactionView, status_code=201, summary="Ingest a transaction")
def ingest_transaction(
    payload: TransactionCreateRequest,
    principal: AdminOrManager,
) -> TransactionView:
    return TransactionView(
        id="txn_stub_created",
        provider=payload.provider,
        external_transaction_id=payload.external_transaction_id,
        amount_minor=payload.amount_minor,
        currency=payload.currency.upper(),
        sender_name=payload.sender_name,
        receiver_name=payload.receiver_name,
        occurred_at=payload.occurred_at,
        status="POSTED",
        source=payload.source_type,
        payment_account_id=payload.payment_account_id,
        trust_level=payload.trust_level,
    )


@router.get("/{transaction_id}", response_model=TransactionView, summary="Read a transaction")
def get_transaction(transaction_id: str, principal: AdminOrManager) -> TransactionView:
    if transaction_id != DEMO_TRANSACTION.id:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return DEMO_TRANSACTION.model_copy(update={"id": transaction_id})
