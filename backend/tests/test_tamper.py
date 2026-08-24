"""Tests for CPU-only image tamper observations."""

from __future__ import annotations

import io

from PIL import Image, PngImagePlugin

from proofpay.extraction.preprocess import prepare
from proofpay.extraction.tamper import TAMPER_VERSION, analyze_tamper


def _make_sample_image(w: int = 1080, h: int = 2400) -> bytes:
    img = Image.new("RGB", (w, h), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestTamperAnalysis:
    def test_computes_phash(self):
        raw = _make_sample_image(1080, 2400)
        prepared = prepare(raw)
        obs = analyze_tamper(raw, prepared)

        # Should contain phash observation
        phash_obs = [o for o in obs if o.code == "IMAGE_PHASH"]
        assert len(phash_obs) == 1
        assert phash_obs[0].severity == "info"
        assert "phash:" in phash_obs[0].detail
        assert phash_obs[0].analyzer_version == TAMPER_VERSION

    def test_editor_metadata_detected(self):
        # Create image with Photoshop signature in metadata
        img = Image.new("RGB", (1080, 2400), color="white")
        meta = PngImagePlugin.PngInfo()
        meta.add_text("Software", "Adobe Photoshop 2024")
        buf = io.BytesIO()
        img.save(buf, format="PNG", pnginfo=meta)
        raw = buf.getvalue()

        prepared = prepare(raw)
        obs = analyze_tamper(raw, prepared)

        editor_obs = [o for o in obs if o.code == "IMAGE_EDITOR_SIGNATURE"]
        assert len(editor_obs) == 1
        assert editor_obs[0].severity == "notice"
        assert "Adobe Photoshop" in editor_obs[0].detail

    def test_no_critical_severity_ever(self):
        raw = _make_sample_image(1080, 2400)
        prepared = prepare(raw)
        obs = analyze_tamper(raw, prepared)

        for o in obs:
            assert o.severity in ("info", "notice")
            assert o.severity != "critical"

    def test_non_standard_aspect_ratio_flagged(self):
        # Square crop (1000x1000) differs from standard phone portrait ratios
        raw = _make_sample_image(1000, 1000)
        prepared = prepare(raw)
        obs = analyze_tamper(raw, prepared)

        ratio_obs = [o for o in obs if o.code == "IMAGE_NON_STANDARD_ASPECT_RATIO"]
        assert len(ratio_obs) == 1
        assert ratio_obs[0].severity == "info"
