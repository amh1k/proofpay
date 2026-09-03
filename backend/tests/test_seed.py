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


#: One seeded case per verdict, and the receipt that reaches it.
#:
#: Track C's "done when" asks that `seed --reset` produce data which reproduces
#: **all five** verification states on demand. The tests above prove the seed is
#: repeatable and that fingerprints are allocation-scoped; neither drives a
#: decision, so neither would notice if the seeded ledger stopped supporting a
#: verdict. This is the test that would.
FIVE_STATES = [
    ("G01", "ORD-G01", "G01.jpg", "VERIFIED"),
    ("S01", "ORD-S01", "S01.jpg", "SUSPICIOUS"),
    ("D01", "ORD-D01", "D01.jpg", "DUPLICATE"),
    ("N01", "ORD-N01", "N01.jpg", "NEEDS_REVIEW"),
    ("U01", "ORD-U01", "U01.jpg", "UNMATCHED"),
]


@pytest.mark.parametrize(("case", "order_ref", "image_name", "expected"), FIVE_STATES)
def test_seeded_data_reproduces_every_verification_state(
    seeded_database, case: str, order_ref: str, image_name: str, expected: str
) -> None:
    """Upload the case's own receipt against its own seeded order, over HTTP.

    Parametrised so a failure names the case rather than reporting "1 of 5".
    Each case gets its own merchant, which is what lets the engine see the ledger
    scope the manifest authored instead of a pooled feed that would change
    retrieval and quietly move the verdict.
    """
    engine, _ = seeded_database
    principal = DemoPrincipal(
        user_id=str(seeded_id("user", case)),
        merchant_id=str(seeded_id("merchant", case)),
        display_name=f"Seeded {case} merchant",
        role=MembershipRole.MERCHANT_ADMIN,
        scopes=(),
    )

    def override_session():
        with Session(engine) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_session] = override_session
    image = FIXTURE_ROOT / "images" / image_name
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/verifications",
            data={"order_id": str(seeded_id("order", f"{case}:{order_ref}"))},
            files={"screenshot": (image.name, image.read_bytes(), "image/jpeg")},
            headers={"Idempotency-Key": f"five-states-{case}"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == expected, (
        f"{case} against its own seeded order returned {body['status']} "
        f"via {body.get('fired_rule_id')}, expected {expected}. "
        "Either the seeded ledger for this case changed or a rule moved; "
        "check which before editing this expectation."
    )
