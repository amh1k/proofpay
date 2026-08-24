"""Migration and database-invariant integration tests for Track B."""

from __future__ import annotations

import datetime as dt
import io
import uuid
from collections import Counter
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from proofpay.db import Base
from proofpay.db.models import (
    AllocationStatus,
    Merchant,
    MerchantMembership,
    MerchantTransaction,
    Order,
    PaymentAccount,
    PaymentClaim,
    PaymentProof,
    TransactionAllocation,
    User,
    VerificationAttempt,
)
from proofpay.db.session import build_engine
from proofpay.main import create_app, database_readiness

BACKEND_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"


@dataclass(frozen=True, slots=True)
class AllocationSeed:
    merchant_id: uuid.UUID
    membership_id: uuid.UUID
    transaction_id: uuid.UUID
    order_id: uuid.UUID
    attempt_id: uuid.UUID


def _alembic_config(database_url: str, *, output_buffer: io.StringIO | None = None) -> Config:
    config = Config(str(ALEMBIC_INI), output_buffer=output_buffer)
    config.attributes["database_url"] = database_url
    return config


@pytest.fixture
def migrated_database(tmp_path: Path) -> Iterator[tuple[str, Config]]:
    database_path = tmp_path / "proofpay.db"
    database_url = f"sqlite:///{database_path}"
    config = _alembic_config(database_url)
    command.upgrade(config, "head")
    yield database_url, config


def _seed_verification(session: Session) -> AllocationSeed:
    now = dt.datetime.now(dt.UTC)
    merchant = Merchant(name="Allocation Race Merchant")
    user = User(email="race-owner@example.com", display_name="Race Owner")
    session.add_all([merchant, user])
    session.flush()

    membership = MerchantMembership(
        merchant_id=merchant.id,
        user_id=user.id,
        role="MERCHANT_ADMIN",
        scope_mode="MERCHANT_WIDE",
        status="ACTIVE",
    )
    account = PaymentAccount(
        merchant_id=merchant.id,
        provider_code="demo",
        display_name="Race account",
    )
    order = Order(
        merchant_id=merchant.id,
        external_order_ref="ORDER-RACE",
        expected_amount_minor=5000,
        currency="PKR",
    )
    session.add_all([membership, account, order])
    session.flush()

    proof = PaymentProof(
        merchant_id=merchant.id,
        uploaded_by_membership_id=membership.id,
        storage_key="proofs/race.png",
        media_type="image/png",
        byte_size=128,
        width_px=100,
        height_px=100,
        sha256_hash="a" * 64,
    )
    session.add(proof)
    session.flush()

    claim = PaymentClaim(
        merchant_id=merchant.id,
        payment_proof_id=proof.id,
        claimed_amount_minor=5000,
        currency="PKR",
        parser_version="test/1",
    )
    transaction = MerchantTransaction(
        merchant_id=merchant.id,
        payment_account_id=account.id,
        provider_code="demo",
        external_transaction_id="TX-RACE",
        amount_minor=5000,
        currency="PKR",
        occurred_at=now,
        ingested_at=now,
        source_type="DEMO",
        trust_level="DEMO_TRUSTED",
    )
    session.add_all([claim, transaction])
    session.flush()

    attempt = VerificationAttempt(
        merchant_id=merchant.id,
        order_id=order.id,
        payment_proof_id=proof.id,
        payment_claim_id=claim.id,
        requested_by_membership_id=membership.id,
        lifecycle_status="DECIDED",
        decision_status="VERIFIED",
        risk_level="LOW",
        decision_confidence=1,
        selected_transaction_id=transaction.id,
        rule_set_version="rules/test",
    )
    session.add(attempt)
    session.commit()
    return AllocationSeed(
        merchant_id=merchant.id,
        membership_id=membership.id,
        transaction_id=transaction.id,
        order_id=order.id,
        attempt_id=attempt.id,
    )


def test_migration_head_matches_model_metadata(
    migrated_database: tuple[str, Config],
) -> None:
    database_url, config = migrated_database
    engine = build_engine(database_url)
    try:
        table_names = set(inspect(engine).get_table_names())
        assert table_names == set(Base.metadata.tables) | {"alembic_version"}
        assert len(ScriptDirectory.from_config(config).get_heads()) == 1
        command.check(config)
    finally:
        engine.dispose()


def test_migration_partial_indexes_have_reviewed_predicates(
    migrated_database: tuple[str, Config],
) -> None:
    database_url, _ = migrated_database
    engine = build_engine(database_url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT name, sql FROM sqlite_master WHERE type = 'index' AND name LIKE 'uq_%'"
                )
            )
            index_sql = {name: sql for name, sql in rows}
    finally:
        engine.dispose()

    assert "WHERE status = 'ACTIVE'" in index_sql["uq_allocation_active_txn"]
    assert "WHERE status = 'ACTIVE'" in index_sql["uq_allocation_active_order"]
    assert "WHERE selected = 1" in index_sql["uq_candidate_selected_attempt"]
    assert (
        "WHERE status IN ('OPEN', 'IN_PROGRESS')"
        in index_sql["uq_review_assignment_active_attempt"]
    )


def test_migration_downgrades_to_base_and_reapplies(
    migrated_database: tuple[str, Config],
) -> None:
    database_url, config = migrated_database
    command.downgrade(config, "base")
    engine = build_engine(database_url)
    try:
        assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = build_engine(database_url)
    try:
        assert set(Base.metadata.tables) <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_migration_compiles_for_postgresql() -> None:
    output = io.StringIO()
    config = _alembic_config(
        "postgresql://proofpay:proofpay@localhost/proofpay",
        output_buffer=output,
    )
    command.upgrade(config, "head", sql=True)
    ddl = output.getvalue()

    assert "JSONB" in ddl
    assert "CREATE UNIQUE INDEX uq_allocation_active_txn" in ddl
    assert "WHERE status = 'ACTIVE'" in ddl


def test_readiness_checks_the_database() -> None:
    engine = build_engine("sqlite://")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with factory() as session:
            assert database_readiness(session) == {"status": "ready", "database": "ok"}
        assert any(getattr(route, "path", None) == "/health/ready" for route in create_app().routes)
    finally:
        engine.dispose()


def test_readiness_returns_503_when_database_is_unavailable() -> None:
    engine = build_engine("sqlite://")
    closed_connection = engine.connect()
    closed_connection.close()
    unavailable_session = Session(bind=closed_connection)
    try:
        with pytest.raises(HTTPException) as raised:
            database_readiness(unavailable_session)
    finally:
        unavailable_session.close()
        engine.dispose()

    assert raised.value.status_code == 503
    assert raised.value.detail == "DATABASE_UNAVAILABLE: Database is unavailable"


def test_tenant_composite_foreign_keys_reject_cross_merchant_rows(
    migrated_database: tuple[str, Config],
) -> None:
    database_url, _ = migrated_database
    engine = build_engine(database_url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with factory() as session:
            seed = _seed_verification(session)
            other_merchant = Merchant(name="Other Merchant")
            other_user = User(email="other@example.com", display_name="Other Owner")
            session.add_all([other_merchant, other_user])
            session.flush()
            other_membership = MerchantMembership(
                merchant_id=other_merchant.id,
                user_id=other_user.id,
                role="MERCHANT_ADMIN",
                scope_mode="MERCHANT_WIDE",
                status="ACTIVE",
            )
            session.add(other_membership)
            session.commit()

            cross_tenant_attempt = VerificationAttempt(
                merchant_id=other_merchant.id,
                order_id=seed.order_id,
                payment_proof_id=session.scalar(select(PaymentClaim.payment_proof_id).limit(1)),
                requested_by_membership_id=other_membership.id,
            )
            session.add(cross_tenant_attempt)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
    finally:
        engine.dispose()


def test_database_constraint_allows_only_one_of_eight_concurrent_allocations(
    migrated_database: tuple[str, Config],
) -> None:
    database_url, _ = migrated_database
    engine = build_engine(database_url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with factory() as session:
            seed = _seed_verification(session)

        writers = 8
        barrier = Barrier(writers)

        def allocate(_: int) -> str:
            with factory() as session:
                allocation = TransactionAllocation(
                    merchant_id=seed.merchant_id,
                    merchant_transaction_id=seed.transaction_id,
                    order_id=seed.order_id,
                    verification_attempt_id=seed.attempt_id,
                )
                session.add(allocation)
                barrier.wait(timeout=10)
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    return "duplicate"
                return "created"

        with ThreadPoolExecutor(max_workers=writers) as executor:
            outcomes = list(executor.map(allocate, range(writers)))

        assert Counter(outcomes) == {"created": 1, "duplicate": writers - 1}

        with factory() as session:
            winner = session.scalars(select(TransactionAllocation)).one()
            winner.status = AllocationStatus.RELEASED
            winner.released_at = dt.datetime.now(dt.UTC)
            winner.released_by_membership_id = seed.membership_id
            winner.release_reason = "Correcting a mistaken allocation"
            session.commit()

            session.add(
                TransactionAllocation(
                    merchant_id=seed.merchant_id,
                    merchant_transaction_id=seed.transaction_id,
                    order_id=seed.order_id,
                    verification_attempt_id=seed.attempt_id,
                )
            )
            session.commit()
            assert session.scalar(select(func.count()).select_from(TransactionAllocation)) == 2
    finally:
        engine.dispose()
