from fastapi.testclient import TestClient

from proofpay.api.v1.stub_data import DEMO_VERIFICATIONS
from proofpay.core.reasons import ReasonCode
from proofpay.main import create_app


def client() -> TestClient:
    return TestClient(create_app())


def auth(token: str = "stub-access-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def upload_headers(key: str = "verification-test-1") -> dict[str, str]:
    return {**auth(), "Idempotency-Key": key}


def test_openapi_exposes_frontend_contract() -> None:
    document = client().get("/openapi.json").json()
    paths = document["paths"]

    assert "/api/v1/verifications" in paths
    assert "/api/v1/verifications/{verification_id}" in paths
    assert "/api/v1/orders" in paths
    assert "/api/v1/transactions" in paths
    assert "/api/v1/dashboard/summary" in paths
    assert "/api/v1/auth/token" in paths
    assert "/api/v1/verifications/{verification_id}/reviews" in paths
    assert "/api/v1/reviews" in paths
    assert "/api/v1/demo/reset" in paths

    verification_post = paths["/api/v1/verifications"]["post"]
    assert verification_post["security"] == [{"OAuth2PasswordBearer": []}]
    assert "Idempotency-Key" in {parameter["name"] for parameter in verification_post["parameters"]}
    assert {"401", "409", "413", "415", "422", "429", "500"}.issubset(
        verification_post["responses"]
    )


def test_create_verification_returns_decision_contract() -> None:
    response = client().post(
        "/api/v1/verifications",
        data={"order_id": "order_demo_1001"},
        files={"screenshot": ("payment.png", b"stub-image", "image/png")},
        headers=upload_headers(),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "VERIFIED"
    assert body["stage"] == "COMPLETE"
    assert body["matched_txn_id"] == "txn_demo_1001"
    assert body["summary"]
    assert body["matched_transaction"]["masked_reference"] == "TX••••01"
    assert body["evidence"][0]["claimed_value"] == "TX1001"
    assert {item["field"] for item in body["evidence"]} >= {
        "reference_id",
        "amount",
        "sender_name",
        "timestamp",
    }


def test_demo_decisions_match_engine_rule_ids_and_reason_types() -> None:
    expected_rules = {
        "VERIFIED": "R090",
        "SUSPICIOUS": "R030",
        "DUPLICATE": "R020",
        "NEEDS_REVIEW": "R050",
        "UNMATCHED": "R010",
    }

    for decision in DEMO_VERIFICATIONS:
        assert decision.fired_rule_id == expected_rules[decision.status]
        assert all(isinstance(reason, ReasonCode) for reason in decision.reasons)


def test_claims_route_is_available_as_deprecated_alias() -> None:
    response = client().post(
        "/api/v1/claims",
        data={"order_id": "order_demo_1001"},
        files={"screenshot": ("payment.png", b"stub-image", "image/png")},
        headers=upload_headers("claim-test-1"),
    )

    assert response.status_code == 201
    assert response.json()["status"] == "VERIFIED"


def test_history_supports_all_demo_states() -> None:
    response = client().get("/api/v1/verifications", headers=auth())

    assert response.status_code == 200
    assert {item["status"] for item in response.json()["items"]} == {
        "VERIFIED",
        "SUSPICIOUS",
        "DUPLICATE",
        "NEEDS_REVIEW",
        "UNMATCHED",
    }


def test_filtering_and_dashboard_are_stable() -> None:
    filtered = client().get(
        "/api/v1/verifications", params={"status": "SUSPICIOUS"}, headers=auth()
    )
    dashboard = client().get("/api/v1/dashboard/summary", headers=auth())

    assert filtered.status_code == 200
    assert [item["status"] for item in filtered.json()["items"]] == ["SUSPICIOUS"]
    assert dashboard.status_code == 200
    assert dashboard.json()["by_status"]["VERIFIED"] == 38


def test_demo_token_shape_is_available_for_frontend() -> None:
    response = client().post(
        "/api/v1/auth/token",
        data={"username": "owner@example.com", "password": "demo"},
    )

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert "claims:submit" in response.json()["scopes"]


def test_invalid_auth_uses_standard_error_envelope() -> None:
    response = client().get("/api/v1/auth/me", headers=auth("not-a-token"))

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_idempotency_replays_same_request_and_rejects_conflict() -> None:
    app_client = client()
    headers = upload_headers("same-key")
    payload = {"order_id": "order_demo_1001"}
    files = {"screenshot": ("payment.png", b"first-image", "image/png")}

    first = app_client.post("/api/v1/verifications", data=payload, files=files, headers=headers)
    replay = app_client.post("/api/v1/verifications", data=payload, files=files, headers=headers)
    conflict = app_client.post(
        "/api/v1/verifications",
        data=payload,
        files={"screenshot": ("payment.png", b"different-image", "image/png")},
        headers=headers,
    )

    assert first.status_code == replay.status_code == 201
    assert first.json()["id"] == replay.json()["id"]
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"


def test_verifier_can_use_assigned_order_but_cannot_read_transactions() -> None:
    rider = auth("stub-access-token:rider")
    allowed = client().get("/api/v1/orders/order_demo_1001", headers=rider)
    forbidden = client().get("/api/v1/transactions", headers=rider)

    assert allowed.status_code == 200
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "FORBIDDEN"


def test_manual_review_and_demo_reset_contracts() -> None:
    reviewer = auth("stub-access-token:reviewer")
    review_queue = client().get("/api/v1/reviews", headers=reviewer)
    review = client().post(
        "/api/v1/verifications/verification_demo_1004/reviews",
        headers=reviewer,
        json={
            "review_outcome": "MORE_EVIDENCE_REQUIRED",
            "reason_code": "AMBIGUOUS_CANDIDATES",
        },
    )
    reset = client().post("/api/v1/demo/reset", headers=auth())

    assert review_queue.status_code == 200
    assert review_queue.json()["total"] == 1
    assert review.status_code == 201
    assert review.json()["review_outcome"] == "MORE_EVIDENCE_REQUIRED"
    assert reset.status_code == 200
    assert reset.json()["status"] == "reset"
