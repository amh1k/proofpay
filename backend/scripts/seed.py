"""Seed deterministic merchant scenarios from the demo manifest.

Run from ``backend`` with ``uv run python scripts/seed.py --reset``.  Each
manifest case gets its own merchant so the engine sees the case's authored
ledger scope instead of a pooled feed that would change retrieval results.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from proofpay.config import get_settings
from proofpay.db import Base
from proofpay.db.models import (
    AllocationStatus,
    MembershipRole,
    MembershipScope,
    MembershipStatus,
    Merchant,
    MerchantMembership,
    MerchantTransaction,
    Order,
    OrderStatus,
    PaymentAccount,
    PaymentClaim,
    PaymentProof,
    ProofRetentionStatus,
    RiskLevel,
    TransactionAllocation,
    TransactionSourceType,
    TransactionStatus,
    TransactionTrustLevel,
    User,
    UserStatus,
    VerificationAttempt,
    VerificationDecisionStatus,
    VerificationLifecycleStatus,
)
from proofpay.db.session import build_engine
from proofpay.demo.clock import PINNED_ANCHOR
from proofpay.storage import LocalStorage, validate_image

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "fixtures" / "demo" / "manifest.json"
IMAGE_ROOT = ROOT / "fixtures" / "demo"
SEED_NAMESPACE = uuid5(NAMESPACE_URL, "https://proofpay.local/demo-seed/v1")
NOW = PINNED_ANCHOR.astimezone(UTC)


def _id(kind: str, value: str) -> UUID:
    return uuid5(SEED_NAMESPACE, f"{kind}:{value}")


def _at(offset_minutes: int) -> datetime:
    return (PINNED_ANCHOR + timedelta(minutes=offset_minutes)).astimezone(UTC)


def _reset_schema(engine: Engine) -> None:
    """Recreate the local schema; this command is the explicit reset boundary."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def _proof_metadata(case_id: str) -> tuple[bytes, str, str, int, int, int]:
    content = (IMAGE_ROOT / "images" / f"{case_id}.jpg").read_bytes()
    validated = validate_image(content, max_bytes=get_settings().max_upload_bytes)
    return (
        validated.stored_bytes,
        validated.stored_sha256,
        validated.stored_media_type,
        validated.stored_size,
        validated.width,
        validated.height,
    )


def _add_order(
    session: Session,
    *,
    merchant_id: UUID,
    case_id: str,
    order_ref: str,
    amount_minor: int,
) -> Order:
    order = Order(
        id=_id("order", f"{case_id}:{order_ref}"),
        merchant_id=merchant_id,
        external_order_ref=order_ref,
        expected_amount_minor=amount_minor,
        currency="PKR",
        status=OrderStatus.PENDING_PAYMENT,
        created_at=_at(-30),
        updated_at=NOW,
    )
    session.add(order)
    return order


def _add_transaction(
    session: Session,
    *,
    merchant_id: UUID,
    account_id: UUID,
    case_id: str,
    row: dict,
    external_id: str | None = None,
    offset_key: str = "ledger_offset_min",
) -> MerchantTransaction:
    transaction = MerchantTransaction(
        id=_id("transaction", f"{case_id}:{external_id or row['external_transaction_id']}"),
        merchant_id=merchant_id,
        payment_account_id=account_id,
        provider_code=row["rail"],
        external_transaction_id=external_id or row["external_transaction_id"],
        amount_minor=row["amount_paisa"],
        currency="PKR",
        sender_name=row.get("sender_name"),
        receiver_name=row.get("receiver_name"),
        occurred_at=_at(row[offset_key]),
        status=TransactionStatus(row["status"]),
        source_type=TransactionSourceType.DEMO,
        trust_level=TransactionTrustLevel.DEMO_TRUSTED,
        source_payload={"manifest_case": case_id},
        ingested_at=NOW,
        created_at=NOW,
    )
    session.add(transaction)
    return transaction


def _add_accepted_proof(
    session: Session,
    storage: LocalStorage,
    *,
    merchant_id: UUID,
    membership_id: UUID,
    case_id: str,
    order: Order,
    transaction: MerchantTransaction,
    visible: dict,
) -> None:
    stored_bytes, stored_sha256, media_type, byte_size, width, height = _proof_metadata(case_id)
    proof_id = _id("proof", f"{case_id}:{order.id}")
    storage_key = f"proofs/{merchant_id}/{stored_sha256[:2]}/{stored_sha256}.png"
    storage.put(storage_key, stored_bytes)
    session.add(
        PaymentProof(
            id=proof_id,
            merchant_id=merchant_id,
            uploaded_by_membership_id=membership_id,
            storage_key=storage_key,
            media_type=media_type,
            byte_size=byte_size,
            width_px=width,
            height_px=height,
            sha256_hash=stored_sha256,
            retention_status=ProofRetentionStatus.ACTIVE,
            uploaded_at=NOW,
        )
    )
    session.flush()
    claim_id = _id("claim", f"{case_id}:{order.id}")
    session.add(
        PaymentClaim(
            id=claim_id,
            merchant_id=merchant_id,
            payment_proof_id=proof_id,
            provider_code=visible.get("rail"),
            claimed_amount_minor=visible.get("amount_paisa"),
            currency="PKR",
            sender_name=visible.get("sender_name"),
            receiver_name=visible.get("receiver_name"),
            external_transaction_id=visible.get("reference_id"),
            claimed_occurred_at=_at(visible.get("claimed_offset_min", 0)),
            timezone_assumption="UTC",
            field_confidences={},
            parser_version="seed-manifest-v1",
            created_at=NOW,
        )
    )
    session.flush()
    attempt_id = _id("accepted-attempt", f"{case_id}:{order.id}")
    session.add(
        VerificationAttempt(
            id=attempt_id,
            merchant_id=merchant_id,
            order_id=order.id,
            payment_proof_id=proof_id,
            payment_claim_id=claim_id,
            requested_by_membership_id=membership_id,
            lifecycle_status=VerificationLifecycleStatus.DECIDED,
            decision_status=VerificationDecisionStatus.VERIFIED,
            risk_level=RiskLevel.LOW,
            decision_confidence=1,
            selected_transaction_id=transaction.id,
            rule_set_version="seed-manifest-v1",
            summary_reason_code="STRONG_FIELD_AGREEMENT",
            started_at=NOW,
            decided_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    session.flush()
    session.add(
        TransactionAllocation(
            id=_id("accepted-allocation", f"{case_id}:{order.id}"),
            merchant_id=merchant_id,
            merchant_transaction_id=transaction.id,
            order_id=order.id,
            verification_attempt_id=attempt_id,
            status=AllocationStatus.ACTIVE,
            allocated_at=NOW,
        )
    )


def seed_database(engine: Engine, *, reset: bool = False) -> dict[str, str]:
    """Seed all manifest scenarios and return the deterministic scenario IDs."""
    if not reset:
        raise ValueError("refusing to seed without --reset")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in manifest["cases"]}
    _reset_schema(engine)
    storage = LocalStorage(get_settings().storage_local_path)
    scenario_merchants: dict[str, str] = {}

    with Session(engine) as session:
        for case_id, case in cases.items():
            merchant_id = _id("merchant", case_id)
            user_id = _id("user", case_id)
            membership_id = _id("membership", case_id)
            scenario_merchants[case_id] = str(merchant_id)
            session.add(
                Merchant(
                    id=merchant_id,
                    name=f"ProofPay Demo — {case_id}",
                    default_currency="PKR",
                    default_timezone="Asia/Karachi",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            session.add(
                User(
                    id=user_id,
                    email=f"{case_id.lower()}@demo.proofpay.local",
                    display_name=f"Demo Merchant {case_id}",
                    status=UserStatus.ACTIVE,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            session.flush()
            session.add(
                MerchantMembership(
                    id=membership_id,
                    merchant_id=merchant_id,
                    user_id=user_id,
                    role=MembershipRole.MERCHANT_ADMIN,
                    scope_mode=MembershipScope.MERCHANT_WIDE,
                    status=MembershipStatus.ACTIVE,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            session.flush()

            accounts: dict[str, PaymentAccount] = {}
            for row in case["ledger"]:
                rail = row["rail"]
                if rail not in accounts:
                    account = PaymentAccount(
                        id=_id("account", f"{case_id}:{rail}"),
                        merchant_id=merchant_id,
                        provider_code=rail,
                        display_name=f"{rail.title()} demo account",
                        created_at=NOW,
                    )
                    accounts[rail] = account
                    session.add(account)
            session.flush()

            order_refs = {case["order"]["external_order_ref"]}
            order_refs.update(a["allocated_to_order_ref"] for a in case.get("allocations", ()))
            order_refs.update(p["submitted_for_order_ref"] for p in case.get("prior_proofs", ()))
            orders_by_ref: dict[str, Order] = {}
            for order_ref in sorted(order_refs):
                source_case = next(
                    source
                    for source in cases.values()
                    if source["order"]["external_order_ref"] == order_ref
                )
                orders_by_ref[order_ref] = _add_order(
                    session,
                    merchant_id=merchant_id,
                    # IDs are globally unique, so include the scenario
                    # merchant even when this order reference comes from a
                    # related manifest case.
                    case_id=case_id,
                    order_ref=order_ref,
                    amount_minor=source_case["order"]["expected_amount_paisa"],
                )
            session.flush()

            transactions_by_external: dict[str, MerchantTransaction] = {}
            for row in case["ledger"]:
                transaction = _add_transaction(
                    session,
                    merchant_id=merchant_id,
                    account_id=accounts[row["rail"]].id,
                    case_id=case_id,
                    row=row,
                )
                transactions_by_external[row["external_transaction_id"]] = transaction
            session.flush()

            # D02 has a prior accepted proof but deliberately no allocation in
            # its authored feed. Give that historical proof a separate settled
            # transaction so the current D02 transaction remains unallocated.
            for prior in case.get("prior_proofs", ()):
                source_case = cases[prior["image_of_case"]]
                source_row = source_case["ledger"][0]
                historical_id = f"HIST-{prior['image_of_case']}-{case_id}"
                account = accounts.get(source_row["rail"])
                if account is None:
                    account = PaymentAccount(
                        id=_id("account", f"{case_id}:{source_row['rail']}"),
                        merchant_id=merchant_id,
                        provider_code=source_row["rail"],
                        display_name=f"{source_row['rail'].title()} demo account",
                        created_at=NOW,
                    )
                    accounts[source_row["rail"]] = account
                    session.add(account)
                    session.flush()
                historical = _add_transaction(
                    session,
                    merchant_id=merchant_id,
                    account_id=account.id,
                    case_id=case_id,
                    row=source_row,
                    external_id=historical_id,
                )
                session.flush()
                _add_accepted_proof(
                    session,
                    storage,
                    merchant_id=merchant_id,
                    membership_id=membership_id,
                    case_id=prior["image_of_case"],
                    order=orders_by_ref[prior["submitted_for_order_ref"]],
                    transaction=historical,
                    visible=source_case["visible"],
                )

            for allocation in case.get("allocations", ()):
                transaction = transactions_by_external[allocation["external_transaction_id"]]
                target_order = orders_by_ref[allocation["allocated_to_order_ref"]]
                target_case = next(
                    source
                    for source in cases.values()
                    if source["order"]["external_order_ref"] == target_order.external_order_ref
                )
                _add_accepted_proof(
                    session,
                    storage,
                    merchant_id=merchant_id,
                    membership_id=membership_id,
                    case_id=target_case["id"],
                    order=target_order,
                    transaction=transaction,
                    visible=target_case["visible"],
                )
            session.flush()
        session.commit()
    return scenario_merchants


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="drop and recreate the configured database before seeding",
    )
    args = parser.parse_args()
    if not args.reset:
        parser.error("--reset is required; refusing to modify an existing database")
    engine = build_engine()
    seeded = seed_database(engine, reset=True)
    print(f"Seeded {len(seeded)} deterministic merchant scenarios")
    for case_id, merchant_id in seeded.items():
        print(f"{case_id}: merchant_id={merchant_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
