"""Deterministic domain inputs for the API-to-engine vertical slice.

This module is deliberately temporary demo infrastructure.  It gives the API
the same five representative scenarios used by the committed receipt fixtures
until the persistence service loads orders, transactions, and allocations from
the database.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status

from proofpay.core.models import Allocation, LedgerTxn, Order
from proofpay.core.money import Money
from proofpay.core.reasons import Source
from proofpay.demo.clock import PINNED_ANCHOR

__all__ = ["DemoEngineCase", "demo_case_for"]


@dataclass(frozen=True, slots=True)
class DemoEngineCase:
    """The domain inputs needed to evaluate one demo order."""

    order: Order
    ledger: tuple[LedgerTxn, ...]
    allocations: tuple[Allocation, ...]


def _at(offset_minutes: int) -> datetime:
    return (PINNED_ANCHOR + timedelta(minutes=offset_minutes)).astimezone(UTC)


def _transaction(
    *,
    txn_id: str,
    amount_minor: int,
    provider: str,
    sender_name: str,
    receiver_name: str = "Ali Traders",
    offset_minutes: int = -12,
) -> LedgerTxn:
    return LedgerTxn(
        txn_id=txn_id,
        external_id=txn_id,
        amount=Money(amount_minor),
        occurred_at=_at(offset_minutes),
        provider=provider,
        sender_name=sender_name,
        receiver_name=receiver_name,
        source=Source.SIMULATOR,
        ingested_at=PINNED_ANCHOR.astimezone(UTC),
    )


_CASES: dict[str, DemoEngineCase] = {
    "order_demo_1001": DemoEngineCase(
        order=Order(
            order_id="order_demo_1001",
            reference="ORD-G01",
            expected=Money(150_000),
            created_at=_at(-30),
        ),
        ledger=(
            _transaction(
                txn_id="EP0000011",
                amount_minor=150_000,
                provider="easypaisa",
                sender_name="Bilal Ahmed Khan",
            ),
        ),
        allocations=(),
    ),
    "order_demo_1002": DemoEngineCase(
        order=Order(
            order_id="order_demo_1002",
            reference="ORD-S01",
            expected=Money(500_000),
            created_at=_at(-30),
        ),
        ledger=(
            _transaction(
                txn_id="EP0000303",
                amount_minor=50_000,
                provider="easypaisa",
                sender_name="Shoaib Malik",
            ),
        ),
        allocations=(),
    ),
    "order_demo_1003": DemoEngineCase(
        order=Order(
            order_id="order_demo_1003",
            reference="ORD-D01",
            expected=Money(150_000),
            created_at=_at(-30),
        ),
        ledger=(
            _transaction(
                txn_id="EP0000011",
                amount_minor=150_000,
                provider="easypaisa",
                sender_name="Bilal Ahmed Khan",
            ),
        ),
        allocations=(Allocation(txn_id="EP0000011", order_id="order_demo_1001"),),
    ),
    "order_demo_1004": DemoEngineCase(
        order=Order(
            order_id="order_demo_1004",
            reference="ORD-N01",
            expected=Money(150_000),
            created_at=_at(-30),
        ),
        ledger=(
            _transaction(
                txn_id="EP0000505",
                amount_minor=120_000,
                provider="easypaisa",
                sender_name="Waqar Younis",
            ),
        ),
        allocations=(),
    ),
    "order_demo_1005": DemoEngineCase(
        order=Order(
            order_id="order_demo_1005",
            reference="ORD-U01",
            expected=Money(150_000),
            created_at=_at(-30),
        ),
        ledger=(),
        allocations=(),
    ),
}


def demo_case_for(order_id: str, merchant_id: str) -> DemoEngineCase:
    """Return a merchant-scoped demo case or a normal API 404."""
    case = _CASES.get(order_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    return replace(
        case,
        order=replace(case.order, merchant_id=merchant_id),
        ledger=tuple(replace(txn, merchant_id=merchant_id) for txn in case.ledger),
    )
