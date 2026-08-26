import json
import pathlib

import pytest

from proofpay.core.reasons import ReasonCode, Source, Status

CASES = json.loads(
    (pathlib.Path(__file__).parents[2] / "fixtures/demo/manifest.json").read_text("utf-8")
)["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_expected_outcome_is_a_real_status(case):
    assert case["expected"]["outcome"] in {s.value for s in Status}


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_expected_reason_is_a_real_reason_code(case):
    assert case["expected"]["reason_code"] in {r.value for r in ReasonCode}


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_ledger_source_is_one_the_engine_trusts(case):
    for row in case.get("ledger") or ():
        assert row["trust_level"] in {s.value for s in Source}
