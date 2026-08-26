"""Contract tests for the order list the merchant picks from.

WHY THIS FILE EXISTS:
    A payment claim is only meaningful against an order.  Until this list held
    all five demo cases, GET /orders returned exactly one order, the frontend
    took items[0], and every screenshot ever uploaded was checked against
    order_demo_1001 — four fifths of the product was unreachable from the live
    path no matter what the presenter clicked.

    The important test here is `test_listed_orders_match_the_engine_case_they
    _will_be_checked_against`.  The order rows are projected out of
    `engine_demo`, and that projection is the only thing standing between the
    demo and its worst failure mode: a button that says one expected amount
    while the verdict rendered underneath it argues with a different one.  If
    that test ever fails, the two halves have drifted and the demo is lying on
    screen — do not relax the assertion, fix the projection.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from proofpay.api.engine_demo import demo_cases
from proofpay.main import create_app

# The order ids in the order engine_demo declares them, which is the order the
# buttons appear in.  Spelled out rather than derived so that a reordering in
# engine_demo has to be an intentional, reviewed edit in two places instead of
# a silent one that quietly moves the buttons under the presenter's finger.
EXPECTED_ORDER_IDS = [
    "order_demo_1001",
    "order_demo_1002",
    "order_demo_1003",
    "order_demo_1004",
    "order_demo_1005",
]

# The one order the VERIFIER (rider) principal is assigned; see
# DEMO_VERIFIER_ORDER_IDS in api/v1/auth.py for why it stays at one.
VERIFIER_ORDER_ID = "order_demo_1001"


def client() -> TestClient:
    return TestClient(create_app())


def auth(token: str = "stub-access-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_orders_list_offers_every_engine_demo_case() -> None:
    response = client().get("/api/v1/orders", headers=auth())

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert [item["id"] for item in body["items"]] == EXPECTED_ORDER_IDS


@pytest.mark.parametrize("order_id", EXPECTED_ORDER_IDS)
def test_every_listed_order_is_individually_readable(order_id: str) -> None:
    response = client().get(f"/api/v1/orders/{order_id}", headers=auth())

    assert response.status_code == 200
    assert response.json()["id"] == order_id


def test_listed_orders_match_the_engine_case_they_will_be_checked_against() -> None:
    """The anti-drift guard: what the picker shows is what the engine evaluates."""
    listed = {
        item["id"]: item for item in client().get("/api/v1/orders", headers=auth()).json()["items"]
    }
    cases = {case.order.order_id: case.order for case in demo_cases()}

    assert listed.keys() == cases.keys()

    for order_id, order in cases.items():
        row = listed[order_id]
        assert row["external_order_ref"] == order.reference
        assert row["expected_amount_minor"] == order.expected.minor
        assert row["currency"] == order.expected.currency
        assert row["created_at"] == order.created_at.isoformat().replace("+00:00", "Z")


def test_listed_orders_carry_a_status_and_do_not_pre_announce_the_verdict() -> None:
    items = client().get("/api/v1/orders", headers=auth()).json()["items"]

    assert {item["status"] for item in items} == {"PAYMENT_REVIEW"}


def test_only_the_assigned_order_names_a_verifier() -> None:
    items = client().get("/api/v1/orders", headers=auth()).json()["items"]
    named = {item["id"]: item["assigned_verifier_name"] for item in items}

    assert named[VERIFIER_ORDER_ID] == "Ali Khan"
    assert all(name is None for order_id, name in named.items() if order_id != VERIFIER_ORDER_ID)


def test_the_username_the_frontend_signs_in_with_reaches_all_five_orders() -> None:
    """The live path, end to end: 'owner' resolves to MERCHANT_ADMIN, which is unscoped."""
    app_client = client()
    token = app_client.post(
        "/api/v1/auth/token",
        data={"username": "owner", "password": "proofpay-demo"},
    ).json()

    assert token["role"] == "MERCHANT_ADMIN"

    listed = app_client.get(
        "/api/v1/orders", headers={"Authorization": f"Bearer {token['access_token']}"}
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == EXPECTED_ORDER_IDS


def test_verifier_still_sees_only_the_order_it_is_assigned() -> None:
    rider = auth("stub-access-token:rider")
    app_client = client()

    listed = app_client.get("/api/v1/orders", headers=rider)
    unassigned = app_client.get("/api/v1/orders/order_demo_1002", headers=rider)

    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [VERIFIER_ORDER_ID]
    # A 404 rather than a 403 on purpose: the boundary does not leak that the
    # order exists at all.
    assert unassigned.status_code == 404


def test_verifier_cannot_submit_a_claim_against_an_unassigned_order() -> None:
    response = client().post(
        "/api/v1/verifications",
        data={"order_id": "order_demo_1002"},
        files={"screenshot": ("S01.jpg", b"unused-the-scope-check-runs-first", "image/jpeg")},
        headers={**auth("stub-access-token:rider"), "Idempotency-Key": "scope-check-1"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_reviewer_still_sees_no_orders_at_all() -> None:
    reviewer = auth("stub-access-token:reviewer")
    app_client = client()

    listed = app_client.get("/api/v1/orders", headers=reviewer)
    single = app_client.get(f"/api/v1/orders/{VERIFIER_ORDER_ID}", headers=reviewer)

    assert listed.status_code == 200
    assert listed.json() == {"items": [], "total": 0}
    assert single.status_code == 404
