"""Tests for fixtures/demo/manifest.json.

These tests verify that:
  - manifest.json exists and is valid JSON
  - Total cases count equals 30
  - All 5 outcome categories are correctly represented with expected counts:
      * VERIFIED: 10
      * UNMATCHED: 4
      * SUSPICIOUS: 6
      * DUPLICATE: 4
      * NEEDS_REVIEW: 6
  - Every case has unique IDs (G01..G10, U01..U04, S01..S06, D01..D04, N01..N06)
  - Every case has required schema fields (id, title, category, visible, order, expected)
  - Money amounts are integer paisa values (no floats)
"""

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "fixtures" / "demo" / "manifest.json"


@pytest.fixture(scope="module")
def manifest_data():
    """Load and parse manifest.json once for the test module."""
    assert MANIFEST_PATH.exists(), f"manifest.json not found at {MANIFEST_PATH}"
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


class TestManifestStructure:
    """Validate top-level manifest properties."""

    def test_file_exists(self):
        assert MANIFEST_PATH.exists()

    def test_version_present(self, manifest_data):
        assert "version" in manifest_data
        assert manifest_data["version"] == "1.0.0"

    def test_total_cases_is_30(self, manifest_data):
        assert manifest_data["total_cases"] == 30
        assert len(manifest_data["cases"]) == 30

    def test_category_distribution(self, manifest_data):
        counts = manifest_data["category_counts"]
        assert counts["VERIFIED"] == 10
        assert counts["UNMATCHED"] == 4
        assert counts["SUSPICIOUS"] == 6
        assert counts["DUPLICATE"] == 4
        assert counts["NEEDS_REVIEW"] == 6


class TestManifestCaseIntegrity:
    """Validate individual case schema and invariants."""

    def test_unique_case_ids(self, manifest_data):
        ids = [c["id"] for c in manifest_data["cases"]]
        assert len(ids) == len(set(ids)), f"Duplicate IDs found: {set(x for x in ids if ids.count(x) > 1)}"

    def test_required_keys_present(self, manifest_data):
        required_keys = {"id", "title", "category", "visible", "order", "expected"}
        for case in manifest_data["cases"]:
            missing = required_keys - set(case.keys())
            assert not missing, f"Case {case.get('id')} missing keys: {missing}"

    def test_integer_money_amounts(self, manifest_data):
        """Monetary amounts must use integer paisa (minor units), never float."""
        for case in manifest_data["cases"]:
            vis = case["visible"]
            if vis.get("amount_paisa") is not None:
                assert isinstance(vis["amount_paisa"], int), f"Case {case['id']} visible amount not int"

            ord_info = case["order"]
            assert isinstance(ord_info["expected_amount_paisa"], int), f"Case {case['id']} order amount not int"

            led = case.get("ledger")
            if led and led.get("amount_paisa") is not None:
                assert isinstance(led["amount_paisa"], int), f"Case {case['id']} ledger amount not int"

    def test_expected_outcomes_match_categories(self, manifest_data):
        """case['category'] must equal case['expected']['outcome']."""
        for case in manifest_data["cases"]:
            assert case["category"] == case["expected"]["outcome"], \
                f"Case {case['id']} category {case['category']} != outcome {case['expected']['outcome']}"
