"""Tests for the generated receipt images.

Verifies that:
  - The images directory exists
  - All 30 cases defined in manifest.json have a corresponding .jpg file
  - None of the images are pristine .png files (they must be compressed .jpgs)
"""

import json
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "fixtures" / "demo" / "manifest.json"
IMAGES_DIR = REPO_ROOT / "fixtures" / "demo" / "images"

@pytest.fixture(scope="module")
def manifest_cases():
    assert MANIFEST_PATH.exists()
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [c["id"] for c in data["cases"]]

class TestImagesDirectory:
    def test_images_dir_exists(self):
        assert IMAGES_DIR.exists(), "Run render_receipts.py and tamper_receipts.py first"

    def test_no_pristine_pngs_remain(self):
        """All images should be compressed JPEGs. No PNGs should remain."""
        pngs = list(IMAGES_DIR.glob("*.png"))
        assert len(pngs) == 0, f"Found unprocessed PNGs: {pngs}"

    def test_all_cases_have_jpg_images(self, manifest_cases):
        """Every case in the manifest must have a corresponding .jpg file."""
        missing = []
        for case_id in manifest_cases:
            img_path = IMAGES_DIR / f"{case_id}.jpg"
            if not img_path.exists():
                missing.append(case_id)
                
        assert not missing, f"Missing JPEG images for cases: {missing}"
