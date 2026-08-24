"""Tests for the generated receipt images.

Verifies that:
  - The images directory exists
  - All 30 cases defined in manifest.json have a corresponding .jpg file
  - None of the images are pristine .png files (they must be compressed .jpgs)
  - The sha256 and byte count the manifest records for each image are the ones
    the file on disk actually has
"""

import hashlib
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "fixtures" / "demo" / "manifest.json"
IMAGES_DIR = REPO_ROOT / "fixtures" / "demo" / "images"

@pytest.fixture(scope="module")
def manifest_data():
    assert MANIFEST_PATH.exists()
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def manifest_cases(manifest_data):
    return [c["id"] for c in manifest_data["cases"]]

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

    def test_manifest_hashes_match_the_bytes_on_disk(self, manifest_data):
        """The recorded sha256 must be the hash the file on disk really has.

        Nothing else in the repo checks this, and the manifest is now the only
        place those hashes live. The failure it guards is silent: re-render or
        re-compress an image, forget to re-run tools/build_manifest.py, and
        `verifications._fixture_case_ids` stops recognising a committed fixture
        (it maps an upload to a case by sha256), so the API answers 422 on a
        demo receipt while every other test stays green.

        A case with no `images` block at all was bootstrapped with
        `build_manifest.py --allow-missing-images` and has never been rendered;
        `test_all_cases_have_jpg_images` is the test that reports it, so this
        one does not pile a second confusing failure on top.
        """
        stale = []
        for case in manifest_data["cases"]:
            images = case.get("images")
            if not images:
                continue

            img_path = IMAGES_DIR / f"{case['id']}.jpg"
            if not img_path.exists():
                continue

            payload = img_path.read_bytes()
            actual_sha = hashlib.sha256(payload).hexdigest()
            if actual_sha != images.get("sha256"):
                stale.append(
                    f"{case['id']}: manifest sha256 {images.get('sha256')} "
                    f"but {img_path.name} hashes to {actual_sha}"
                )
            elif len(payload) != images.get("bytes"):
                stale.append(
                    f"{case['id']}: manifest bytes {images.get('bytes')} "
                    f"but {img_path.name} is {len(payload)} bytes"
                )

        assert not stale, (
            "The manifest disagrees with the images on disk. The manifest is "
            "GENERATED -- do not edit the JSON; re-run tools/build_manifest.py, "
            "which recomputes these hashes from the committed files:\n  " + "\n  ".join(stale)
        )
