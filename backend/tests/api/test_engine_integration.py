"""API-owned vertical-slice tests for extraction, decisioning, and mapping."""

from __future__ import annotations

from datetime import UTC
from pathlib import Path

import pytest
from fastapi import HTTPException

from proofpay.api.engine_demo import demo_case_for
from proofpay.api.verification_mapper import verification_result_from_decision
from proofpay.api.verification_service import _extract_claim
from proofpay.core.decide import DecisionPolicy, decide
from proofpay.demo.clock import PINNED_ANCHOR

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "demo" / "images"
MERCHANT_ID = "merchant_demo_001"


@pytest.mark.parametrize(
    ("order_id", "image", "expected_status", "expected_rule"),
    [
        ("order_demo_1001", "G01.jpg", "VERIFIED", "R090"),
        ("order_demo_1002", "S01.jpg", "SUSPICIOUS", "R030"),
        ("order_demo_1003", "D01.jpg", "DUPLICATE", "R020"),
        ("order_demo_1004", "N01.jpg", "NEEDS_REVIEW", "R070"),
        ("order_demo_1005", "U01.jpg", "UNMATCHED", "R010"),
    ],
)
def test_fixture_upload_reaches_real_decision_and_api_mapping(
    order_id: str,
    image: str,
    expected_status: str,
    expected_rule: str,
) -> None:
    verification_id = f"verification_test_{order_id}"
    claim = _extract_claim(
        (FIXTURES / image).read_bytes(),
        verification_id=verification_id,
        merchant_id=MERCHANT_ID,
    )
    case = demo_case_for(order_id, MERCHANT_ID)
    evaluated_at = PINNED_ANCHOR.astimezone(UTC)

    decision = decide(
        claim,
        case.order,
        case.ledger,
        case.allocations,
        now=evaluated_at,
        policy=DecisionPolicy(),
    )
    result = verification_result_from_decision(
        decision,
        claim=claim,
        order=case.order,
        ledger=case.ledger,
        verification_id=verification_id,
        created_at=evaluated_at,
    )

    assert result.status == expected_status
    assert result.fired_rule_id == expected_rule
    assert result.id == verification_id
    assert result.claim.proof_id == verification_id
    assert result.summary
    result.model_dump(mode="json")


def test_deterministic_extraction_is_bound_to_uploaded_fixture_bytes() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _extract_claim(
            b"this is not a committed receipt",
            verification_id="verification_invalid",
            merchant_id=MERCHANT_ID,
        )
    assert exc_info.value.status_code == 422

    # Assert what the message must DO, not how it is worded. The old assertion
    # pinned the exact phrase "committed synthetic demo fixtures", which is the
    # implementation talking: the person who reads this is usually someone at a
    # demo who has just dropped in their own screenshot, and they cannot act on
    # the name of an extractor. So the refusal has to say what would make it
    # work, and it must not leak internals.
    detail = str(exc_info.value.detail)
    assert "Qwen-VL key" in detail, f"the refusal must say what would make it work: {detail!r}"
    assert "extractor" not in detail.lower(), f"names an internal: {detail!r}"
