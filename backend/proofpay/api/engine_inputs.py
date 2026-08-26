"""Map persistence records into the pure verification-engine contracts."""

from __future__ import annotations

from datetime import UTC, datetime

from proofpay.core.models import Allocation, LedgerTxn, Order, PaymentClaim
from proofpay.core.money import Money
from proofpay.core.reasons import Source
from proofpay.core.timex import ClaimedInstant
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


def claim_to_engine(record) -> PaymentClaim:
    """Convert one persisted parser claim back into the engine contract."""
    occurred_at = (
        ClaimedInstant(
            resolved_utc=as_utc(record.claimed_occurred_at),
            assumed_tz=record.timezone_assumption or "UTC",
        )
        if record.claimed_occurred_at
        else None
    )
    amount = (
        Money(record.claimed_amount_minor, record.currency)
        if record.claimed_amount_minor is not None and record.currency
        else None
    )
    return PaymentClaim(
        claim_id=str(record.id),
        merchant_id=str(record.merchant_id),
        proof_id=str(record.payment_proof_id),
        provider=record.provider_code,
        amount=amount,
        sender_name=record.sender_name,
        receiver_name=record.receiver_name,
        reference_id=record.external_transaction_id,
        occurred_at=occurred_at,
        field_confidences=record.field_confidences,
        parser_version=record.parser_version,
    )


__all__ = [
    "allocation_to_engine",
    "as_utc",
    "claim_to_engine",
    "order_to_engine",
    "transaction_to_engine",
]
