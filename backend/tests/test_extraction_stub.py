"""Tests for the extraction pipeline — schema, normalisation, preprocessing, and stub."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from proofpay.extraction.normalize import normalize_msisdn, parse_amount, parse_timestamp
from proofpay.extraction.preprocess import PREPROC_VERSION, prepare, smart_resize
from proofpay.extraction.schema import (
    ExtractionResult,
    Maybe,
    RawClaim,
    compute_confidence_band,
)
from proofpay.extraction.stub import OfflineStubExtractor

FIXTURES = Path(__file__).parents[2] / "fixtures" / "demo"
MANIFEST = FIXTURES / "manifest.json"


# ── Maybe[T] invariants ────────────────────────────────────────────────────

class TestMaybe:
    def test_value_requires_raw_text(self):
        with pytest.raises(ValueError, match="raw_text"):
            Maybe(value="5000")

    def test_value_and_absent_reason_contradictory(self):
        with pytest.raises(ValueError, match="contradictory"):
            Maybe(value="5000", raw_text="5000", absent_reason="illegible")

    def test_null_gets_default_absent_reason(self):
        m = Maybe()
        assert m.value is None
        assert m.absent_reason == "not_present"
        assert not m.ok

    def test_valid_value(self):
        m = Maybe(value="PKR 5,000", raw_text="PKR 5,000")
        assert m.ok
        assert m.absent_reason is None

    def test_explicit_absent_reason(self):
        m = Maybe(absent_reason="illegible")
        assert not m.ok
        assert m.absent_reason == "illegible"


# ── Amount parsing ──────────────────────────────────────────────────────────

class TestParseAmount:
    @pytest.mark.parametrize("raw,expected_minor", [
        ("Rs. 4,500/-", 450000),
        ("PKR 4500.00", 450000),
        ("4,500", 450000),
        ("4500", 450000),
        ("Rs 1,500.50", 150050),
        ("₨ 150000", 15000000),
        ("Rs.500", 50000),
        ("PKR 85,000", 8500000),
        ("200000", 20000000),
    ])
    def test_parses_pakistani_amounts(self, raw, expected_minor):
        result = parse_amount(raw)
        assert result is not None
        assert result.minor == expected_minor

    @pytest.mark.parametrize("raw", [None, "", "   ", "N/A", "---"])
    def test_returns_none_on_unparseable(self, raw):
        assert parse_amount(raw) is None

    def test_ocr_glyph_fixup(self):
        # O → 0 glyph confusion
        result = parse_amount("45OO")
        assert result is not None
        assert result.minor == 450000


# ── Timestamp parsing ───────────────────────────────────────────────────────

class TestParseTimestamp:
    @pytest.mark.parametrize("raw", [
        "20 Aug 2026, 01:54 PM",
        "20 Aug 2026, 02:05 PM",
        "15 Aug 2026, 02:05 PM",
    ])
    def test_parses_receipt_timestamps(self, raw):
        result = parse_timestamp(raw)
        assert result is not None
        assert result.resolved_utc is not None

    def test_date_only(self):
        result = parse_timestamp("20 Aug 2026")
        assert result is not None
        assert result.date_inferred is True

    @pytest.mark.parametrize("raw", [None, "", "unknown", "yesterday"])
    def test_returns_none_on_unparseable(self, raw):
        assert parse_timestamp(raw) is None


# ── Phone number normalisation ──────────────────────────────────────────────

class TestNormalizeMsisdn:
    @pytest.mark.parametrize("raw,expected", [
        ("0301-4567890", "03014567890"),
        ("+92 301 456 7890", "03014567890"),
        ("03014567890", "03014567890"),
    ])
    def test_normalises_pk_mobiles(self, raw, expected):
        assert normalize_msisdn(raw) == expected

    def test_masked_number_preserved(self):
        result = normalize_msisdn("0301-****890")
        assert result is not None
        assert "****" in result or "XXXX" in result.upper()

    @pytest.mark.parametrize("raw", [None, "", "hello", "12345"])
    def test_returns_none_on_invalid(self, raw):
        assert normalize_msisdn(raw) is None


# ── Preprocessing ───────────────────────────────────────────────────────────

class TestPreprocess:
    def _make_jpeg(self, w: int, h: int) -> bytes:
        img = Image.new("RGB", (w, h), color="white")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return buf.getvalue()

    def test_prepare_returns_prepared_image(self):
        raw = self._make_jpeg(1080, 2340)
        result = prepare(raw)
        assert result.preproc_version == PREPROC_VERSION
        assert result.source_sha256 != result.prepared_sha256
        assert result.est_image_tokens > 0

    def test_prepare_is_deterministic(self):
        raw = self._make_jpeg(800, 600)
        r1 = prepare(raw)
        r2 = prepare(raw)
        assert r1.prepared_sha256 == r2.prepared_sha256
        assert r1.png_bytes == r2.png_bytes

    def test_smart_resize_snaps_to_factor(self):
        h, w = smart_resize(1080, 2340)
        assert h % 32 == 0
        assert w % 32 == 0

    def test_smart_resize_respects_max_pixels(self):
        h, w = smart_resize(4000, 8000)
        assert h * w <= 32 * 32 * 4096


# ── Confidence band ─────────────────────────────────────────────────────────

class TestConfidenceBand:
    def test_high_when_grounded_and_valid(self):
        assert compute_confidence_band(True, True, "agree", True) == "high"

    def test_low_when_disagree(self):
        assert compute_confidence_band(True, True, "disagree", True) == "low"

    def test_low_when_not_grounded(self):
        assert compute_confidence_band(False, True, "agree", True) == "low"

    def test_none_when_no_value(self):
        assert compute_confidence_band(True, True, "agree", False) == "none"


# ── Offline stub extractor ──────────────────────────────────────────────────

class TestOfflineStub:
    @pytest.fixture
    def extractor(self):
        return OfflineStubExtractor(MANIFEST)

    def test_extracts_g01(self, extractor):
        img_path = FIXTURES / "images" / "G01.jpg"
        if not img_path.exists():
            pytest.skip("Demo images not present")
        claim = extractor.extract(img_path.read_bytes(), claim_id="test-g01")
        assert claim.claim_id == "test-g01"
        assert claim.amount is not None
        assert claim.amount.minor == 150000
        assert claim.provider == "easypaisa"
        assert claim.sender_name == "Bilal Ahmed Khan"
        assert claim.reference_id == "EP0000011"

    def test_unknown_image_raises(self, extractor):
        with pytest.raises(ValueError, match="not found"):
            extractor.extract(b"not-a-real-image-hash", claim_id="bad")


# ── ExtractionResult ────────────────────────────────────────────────────────

class TestExtractionResult:
    def test_minimal_result(self):
        r = ExtractionResult(
            claim=RawClaim(),
            extractor_id="test/v1",
            preproc_version=PREPROC_VERSION,
        )
        assert r.degraded is False
        assert r.latency_ms == 0

    def test_degraded_result(self):
        r = ExtractionResult(
            claim=RawClaim(),
            extractor_id="fallback/v1",
            preproc_version=PREPROC_VERSION,
            degraded=True,
            degraded_reason="API key missing",
        )
        assert r.degraded is True
