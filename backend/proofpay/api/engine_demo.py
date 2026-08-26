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

__all__ = ["DemoEngineCase", "demo_case_for", "demo_cases"]


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


# ── The presentation order ────────────────────────────────────────
# The declaration order of this dict IS the order the merchant sees the orders
# in, because `demo_cases()` hands `_CASES.values()` straight to the order list
# and Python preserves dict literal order.  It is deliberately narrative:
#
#     1001  the payment that is fine      ->  VERIFIED
#     1002  the edited amount             ->  SUSPICIOUS
#     1003  the receipt used twice        ->  DUPLICATE
#     1004  the one a human must judge    ->  NEEDS_REVIEW
#     1005  the payment we never received ->  UNMATCHED
#
# Show the happy path first so the audience learns what "normal" looks like
# before the failures land.  There is deliberately no second, hand-maintained
# list of these ids anywhere: a sorted() or a dict comprehension over this
# would let the buttons move between runs and slide out from under the
# presenter's finger mid-demo.  Reorder here, or not at all.
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


def demo_cases() -> tuple[DemoEngineCase, ...]:
    """Return every demo case, in the presentation order declared above.

    This exists so the order list the merchant picks from can be *projected*
    from the cases the engine will actually evaluate, instead of being typed
    out a second time in `api/v1/stub_data.py`.  Two hand-kept lists of the
    same five orders drift the moment anyone edits one of them, and the way
    that drift shows up is the worst possible way: the screen promises
    "Rs 1,500 expected" and the verdict underneath it argues with the number
    printed directly above it, live, on a projector.

    The cases are returned unscoped — no merchant_id is stamped on them.  Only
    `demo_case_for` does that, because only a request knows whose merchant it
    is.  Callers that merely want to describe an order (its reference, its
    expected amount) do not need the scoping and must not fake a merchant to
    get it.
    """
    return tuple(_CASES.values())


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
