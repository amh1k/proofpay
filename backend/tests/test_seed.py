"""End-to-end checks for the deterministic demo database seed."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from proofpay.api.v1.auth import DemoPrincipal, get_current_principal
from proofpay.api.v1.schemas import MembershipRole
from proofpay.api.verification_service import _storage_service
from proofpay.config import get_settings
from proofpay.db.models import (
    Merchant,
    MerchantMembership,
    MerchantTransaction,
    Order,
    PaymentProof,
    TransactionAllocation,
)
from proofpay.db.repositories.proof_fingerprints import list_accepted_for_engine
from proofpay.db.session import build_engine, get_session
from proofpay.main import create_app
from proofpay.storage import validate_image
from scripts.seed import seed_database

SEED_NAMESPACE = uuid5(NAMESPACE_URL, "https://proofpay.local/demo-seed/v1")
FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "demo"


def seeded_id(kind: str, value: str) -> UUID:
    return uuid5(SEED_NAMESPACE, f"{kind}:{value}")


@pytest.fixture
def seeded_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator:
    settings = get_settings()
    monkeypatch.setattr(settings, "storage_local_path", str(tmp_path / "proofs"))
    _storage_service.cache_clear()
    engine = build_engine("sqlite://")
    try:
        seeded = seed_database(engine, reset=True)
        yield engine, seeded
    finally:
        _storage_service.cache_clear()
        engine.dispose()


def test_reset_seeds_all_cases_and_is_repeatable(seeded_database) -> None:
    engine, first = seeded_database
    with Session(engine) as session:
        counts = {
            table: session.scalar(select(func.count()).select_from(model))
            for table, model in {
                "merchants": Merchant,
                "memberships": MerchantMembership,
                "orders": Order,
                "transactions": MerchantTransaction,
            }.items()
        }
    assert len(first) == 30
    assert counts == {
        "merchants": 30,
        "memberships": 30,
        "orders": 33,
        "transactions": 29,
    }

    second = seed_database(engine, reset=True)
    assert second == first


def test_seeded_fingerprints_include_only_allocated_proofs(seeded_database) -> None:
    engine, _ = seeded_database
    merchant_id = seeded_id("merchant", "D02")
    with Session(engine) as session:
        fingerprints = list_accepted_for_engine(session, merchant_id)
        proof_count = session.scalar(
            select(func.count()).select_from(PaymentProof).where(PaymentProof.merchant_id == merchant_id)
        )
        allocation_count = session.scalar(
            select(func.count())
            .select_from(TransactionAllocation)
            .where(TransactionAllocation.merchant_id == merchant_id)
        )
    assert proof_count == allocation_count == 1
    assert len(fingerprints) == 1
    assert fingerprints[0].order_ref == "ORD-G02"
    expected_hash = validate_image(
        (FIXTURE_ROOT / "images" / "G02.jpg").read_bytes(),
        max_bytes=get_settings().max_upload_bytes,
    ).stored_sha256
    assert fingerprints[0].sha256 == expected_hash


def test_seeded_http_verification_reuses_an_accepted_screenshot(seeded_database) -> None:
    engine, _ = seeded_database
    principal = DemoPrincipal(
        user_id=str(seeded_id("user", "D02")),
        merchant_id=str(seeded_id("merchant", "D02")),
        display_name="Seeded D02 merchant",
        role=MembershipRole.MERCHANT_ADMIN,
        scopes=(),
    )

    def override_session():
        with Session(engine) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_session] = override_session
    image = FIXTURE_ROOT / "images" / "D02.jpg"
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/verifications",
            data={"order_id": str(seeded_id("order", "D02:ORD-D02"))},
            files={"screenshot": (image.name, image.read_bytes(), "image/jpeg")},
            headers={"Idempotency-Key": "seeded-d02"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "DUPLICATE"
    assert "PROOF_REUSED" in body["reasons"]
    assert "ORD-G02" in body["summary"]


def test_seeded_http_verification_is_tenant_scoped(seeded_database) -> None:
    engine, _ = seeded_database
    principal = DemoPrincipal(
        user_id=str(seeded_id("user", "G01")),
        merchant_id=str(seeded_id("merchant", "G01")),
        display_name="Seeded G01 merchant",
        role=MembershipRole.MERCHANT_ADMIN,
        scopes=(),
    )

    def override_session():
        with Session(engine) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_session] = override_session
    image = FIXTURE_ROOT / "images" / "D02.jpg"
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/verifications",
            data={"order_id": str(seeded_id("order", "D02:ORD-D02"))},
            files={"screenshot": (image.name, image.read_bytes(), "image/jpeg")},
            headers={"Idempotency-Key": "cross-tenant"},
        )
    assert response.status_code == 404
