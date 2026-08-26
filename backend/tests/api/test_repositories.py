"""Tests for merchant-scoped repositories and persistence-to-engine mappers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from proofpay.api.engine_inputs import (
    allocation_to_engine,
    as_utc,
    order_to_engine,
    transaction_to_engine,
)
from proofpay.core.reasons import Source
from proofpay.db import Base
from proofpay.db.models import (
    AllocationStatus,
    Merchant,
    MerchantTransaction,
    Order,
    PaymentAccount,
    TransactionAllocation,
    TransactionSourceType,
    TransactionStatus,
)
from proofpay.db.repositories import orders, transactions
from proofpay.db.session import build_engine


def test_order_and_transaction_repositories_are_merchant_scoped() -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            merchant_a = Merchant(name="Merchant A")
            merchant_b = Merchant(name="Merchant B")
            session.add_all([merchant_a, merchant_b])
            session.flush()

            account_a = PaymentAccount(
                merchant_id=merchant_a.id,
                provider_code="demo",
                display_name="A account",
            )
            account_b = PaymentAccount(
                merchant_id=merchant_b.id,
                provider_code="demo",
                display_name="B account",
            )
            order_a = Order(
                merchant_id=merchant_a.id,
                external_order_ref="A-ORDER",
                expected_amount_minor=150_000,
                currency="PKR",
            )
            order_b = Order(
                merchant_id=merchant_b.id,
                external_order_ref="B-ORDER",
                expected_amount_minor=150_000,
                currency="PKR",
            )
            session.add_all([account_a, account_b, order_a, order_b])
            session.flush()

            posted_a = MerchantTransaction(
                merchant_id=merchant_a.id,
                payment_account_id=account_a.id,
                provider_code="demo",
                external_transaction_id="A-POSTED",
                amount_minor=150_000,
                currency="PKR",
                occurred_at=datetime(2026, 8, 20, 9, 0),
                ingested_at=datetime(2026, 8, 20, 9, 1),
                source_type=TransactionSourceType.DEMO,
                status=TransactionStatus.POSTED,
            )
            reversed_a = MerchantTransaction(
                merchant_id=merchant_a.id,
                payment_account_id=account_a.id,
                provider_code="demo",
                external_transaction_id="A-REVERSED",
                amount_minor=150_000,
                currency="PKR",
                occurred_at=datetime(2026, 8, 20, 9, 2),
                ingested_at=datetime(2026, 8, 20, 9, 3),
                source_type=TransactionSourceType.DEMO,
                status=TransactionStatus.REVERSED,
            )
            posted_b = MerchantTransaction(
                merchant_id=merchant_b.id,
                payment_account_id=account_b.id,
                provider_code="demo",
                external_transaction_id="B-POSTED",
                amount_minor=150_000,
                currency="PKR",
                occurred_at=datetime(2026, 8, 20, 9, 0),
                ingested_at=datetime(2026, 8, 20, 9, 1),
                source_type=TransactionSourceType.DEMO,
                status=TransactionStatus.POSTED,
            )
            session.add_all([posted_a, reversed_a, posted_b])
            session.flush()

            assert orders.get_for_merchant(session, merchant_a.id, order_a.id) is order_a
            assert orders.get_for_merchant(session, merchant_a.id, order_b.id) is None
            assert orders.get_for_merchant(session, merchant_a.id, "not-a-uuid") is None

            result = transactions.list_for_engine(session, merchant_a.id)
            assert result == (posted_a,)
            assert transactions.get_for_merchant(session, merchant_a.id, posted_b.id) is None
    finally:
        engine.dispose()


def test_persistence_records_map_to_engine_contracts() -> None:
    merchant_id = uuid4()
    order_id = uuid4()
    transaction_id = uuid4()
    attempt_id = uuid4()
    naive_time = datetime(2026, 8, 20, 9, 0)

    order = Order(
        id=order_id,
        merchant_id=merchant_id,
        external_order_ref="ORD-1",
        expected_amount_minor=150_000,
        currency="PKR",
        created_at=naive_time,
    )
    transaction = MerchantTransaction(
        id=transaction_id,
        merchant_id=merchant_id,
        provider_code="demo",
        external_transaction_id="TX-1",
        amount_minor=150_000,
        currency="PKR",
        sender_name="Bilal Ahmed Khan",
        receiver_name="Ali Traders",
        occurred_at=naive_time,
        ingested_at=naive_time,
        source_type=TransactionSourceType.DEMO,
        source_payload={"fixture": "G01"},
    )
    allocation = TransactionAllocation(
        merchant_id=merchant_id,
        merchant_transaction_id=transaction_id,
        order_id=order_id,
        verification_attempt_id=attempt_id,
        status=AllocationStatus.ACTIVE,
        allocated_at=naive_time,
    )

    core_order = order_to_engine(order)
    core_transaction = transaction_to_engine(transaction)
    core_allocation = allocation_to_engine(allocation)

    assert core_order.order_id == str(order_id)
    assert core_order.expected.minor == 150_000
    assert core_order.reference == "ORD-1"
    assert core_transaction.txn_id == str(transaction_id)
    assert core_transaction.external_id == "TX-1"
    assert core_transaction.source is Source.SIMULATOR
    assert core_transaction.occurred_at == naive_time.replace(tzinfo=UTC)
    assert core_transaction.raw == {"fixture": "G01"}
    assert core_allocation.txn_id == str(transaction_id)
    assert core_allocation.order_id == str(order_id)
    assert core_allocation.verification_id == str(attempt_id)
    assert as_utc(None) is None
