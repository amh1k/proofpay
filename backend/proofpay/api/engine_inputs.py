"""Map persistence records into the pure verification-engine contracts."""

from __future__ import annotations

from datetime import UTC, datetime

from proofpay.core.models import Allocation, LedgerTxn, Order
from proofpay.core.money import Money
from proofpay.core.reasons import Source
from proofpay.db.models import (
    MerchantTransaction,
    Order as OrderRecord,
    TransactionAllocation,
    TransactionSourceType,
)

_SOURCE_BY_TYPE = {
    TransactionSourceType.PROVIDER: Source.PROVIDER_API,
    TransactionSourceType.WEBHOOK: Source.PROVIDER_API,
    TransactionSourceType.CSV: Source.MERCHANT_CSV,
    TransactionSourceType.MANUAL: Source.MANUAL_ENTRY,
    TransactionSourceType.DEMO: Source.SIMULATOR,
}


def as_utc(value: datetime | None) -> datetime | None:
    """Normalise DB timestamps, including SQLite's naive round-trip values."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def order_to_engine(record: OrderRecord) -> Order:
    """Convert one persisted order into the engine's immutable contract."""
    return Order(
        order_id=str(record.id),
        merchant_id=str(record.merchant_id),
        expected=Money(record.expected_amount_minor, record.currency),
        created_at=as_utc(record.created_at),
        reference=record.external_order_ref or record.customer_reference,
    )


def transaction_to_engine(record: MerchantTransaction) -> LedgerTxn:
    """Convert one persisted ledger transaction into an engine input."""
    source = _SOURCE_BY_TYPE[record.source_type]
    return LedgerTxn(
        txn_id=str(record.id),
        merchant_id=str(record.merchant_id),
        external_id=record.external_transaction_id,
        amount=Money(record.amount_minor, record.currency),
        occurred_at=as_utc(record.occurred_at),
        provider=record.provider_code,
        sender_name=record.sender_name,
        receiver_name=record.receiver_name,
        source=source,
        ingested_at=as_utc(record.ingested_at),
        raw=record.source_payload or {},
    )


def allocation_to_engine(record: TransactionAllocation) -> Allocation:
    """Convert one active persisted allocation into an engine input."""
    return Allocation(
        txn_id=str(record.merchant_transaction_id),
        order_id=str(record.order_id),
        verification_id=str(record.verification_attempt_id),
        allocated_at=as_utc(record.allocated_at),
    )


__all__ = [
    "allocation_to_engine",
    "as_utc",
    "order_to_engine",
    "transaction_to_engine",
]
