"""Receipt Image Renderer — Generates PNG screenshots from manifest.json.

WHY THIS FILE EXISTS:
    This script reads every case from fixtures/demo/manifest.json,
    populates the matching HTML template (easypaisa, jazzcash, raast, bank)
    with the case's `visible` block data, and uses Playwright to render
    a high-resolution mobile screenshot (1080×2340 pixels at 3x DPI).

    For SUSPICIOUS cases (S01–S06), it first renders the CLEAN base image
    using the LEDGER (real) values, then calls the tamper pipeline to
    create the TAMPERED variant that the customer would submit.

FLOW:
    manifest.json → populate HTML template → Playwright screenshot → base PNG
    For SUSPICIOUS cases: base PNG → Pillow pixel-space tamper → tampered PNG

OUTPUT:
    fixtures/demo/images/
      G01.png, G02.png, ..., G10.png   (clean VERIFIED receipts)
      U01.png, ..., U04.png            (clean UNMATCHED receipts)
      S01_base.png, S01.png, ...       (base + tampered SUSPICIOUS receipts)
      D01.png, ..., D04.png            (clean DUPLICATE receipts — reuse G0x)
      N01.png, ..., N06.png            (clean NEEDS_REVIEW receipts)

USAGE:
    python tools/render_receipts.py           # Render all 30 cases
    python tools/render_receipts.py --case G01  # Render a single case
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

# ── Paths ──────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
MANIFEST_PATH = REPO_ROOT / "fixtures" / "demo" / "manifest.json"
OUTPUT_DIR = REPO_ROOT / "fixtures" / "demo" / "images"

# ── Template mapping: rail name → HTML file ────────────────────────
TEMPLATE_MAP = {
    "easypaisa": TEMPLATE_DIR / "easypaisa.html",
    "jazzcash":  TEMPLATE_DIR / "jazzcash.html",
    "raast":     TEMPLATE_DIR / "raast.html",
    "bank":      TEMPLATE_DIR / "bank.html",
}

# ── Viewport dimensions ───────────────────────────────────────────
# 375×812 CSS pixels at 3x device scale = 1125×2436 actual pixels.
# This matches iPhone X/11/12/13/14 Pro dimensions — a common
# screenshot size that Pakistani users would actually submit.
VIEWPORT_WIDTH = 375
VIEWPORT_HEIGHT = 812
DEVICE_SCALE = 3


def format_amount(paisa: int) -> str:
    """Convert paisa (minor units) to display format.

    150000 → '1,500.00'
    50000  → '500.00'

    Pakistani convention: comma every 3 digits, 2 decimal places.
    """
    rupees = paisa / 100
    return f"{rupees:,.2f}"


def populate_template(template_html: str, case: dict) -> str:
    """Replace {{placeholders}} in the HTML template with case data.

    Args:
        template_html: Raw HTML string with {{placeholders}}.
        case:          A single case dict from manifest.json.

    Returns:
        HTML string with all placeholders replaced by actual values.
    """
    visible = case["visible"]

    # For SUSPICIOUS cases, we render the VISIBLE (tampered) values
    # because the image should show what the fraudster wants us to see.
    amount_display = format_amount(visible["amount_paisa"])
    reference_id = visible.get("reference_id") or "N/A"
    timestamp_text = visible.get("raw_timestamp_text") or "—"
    sender_name = visible.get("sender_name") or "Unknown"
    receiver_name = visible.get("receiver_name") or "Unknown"

    # Short time for the status bar (e.g. "1:54 PM")
    # Extract from raw_timestamp_text if it contains a comma
    if "," in timestamp_text:
        time_short = timestamp_text.split(",")[-1].strip()
    else:
        time_short = "2:05 PM"

    replacements = {
        "{{amount_display}}": amount_display,
        "{{reference_id}}":   reference_id,
        "{{timestamp_text}}": timestamp_text,
        "{{sender_name}}":    sender_name,
        "{{receiver_name}}":  receiver_name,
        "{{time_short}}":     time_short,
    }

    result = template_html
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, value)

    return result


def render_case(page, case: dict, output_dir: Path) -> Path:
    """Render a single case to a PNG screenshot.

    Args:
        page:       Playwright page object.
        case:       A single case dict from manifest.json.
        output_dir: Directory to save the PNG file.

    Returns:
        Path to the rendered PNG file.
    """
    rail = case["visible"]["rail"]
    case_id = case["id"]

    # Load the correct HTML template for this payment rail
    template_path = TEMPLATE_MAP.get(rail)
    if not template_path or not template_path.exists():
        print(f"  ⚠ No template for rail '{rail}', skipping {case_id}")
        return None

    template_html = template_path.read_text(encoding="utf-8")

    # Populate the template with this case's visible data
    populated_html = populate_template(template_html, case)

    # Write the populated HTML to a temp file so Playwright can load it
    temp_html = output_dir / f"_temp_{case_id}.html"
    temp_html.write_text(populated_html, encoding="utf-8")

    # Navigate to the temp file and take a screenshot
    page.goto(f"file:///{temp_html.resolve()}")
    page.wait_for_load_state("networkidle")

    # Determine output filename
    out_path = output_dir / f"{case_id}.png"
    page.screenshot(path=str(out_path), full_page=True)

    # Clean up temp HTML
    temp_html.unlink()

    return out_path


def main():
    parser = argparse.ArgumentParser(description="Render receipt images from manifest.json")
    parser.add_argument("--case", type=str, help="Render only this case ID (e.g. G01)")
    args = parser.parse_args()

    # Load manifest
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    cases = manifest["cases"]
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            print(f"✗ Case '{args.case}' not found in manifest")
            sys.exit(1)

    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Rendering {len(cases)} receipt image(s)...")
    print(f"Output: {OUTPUT_DIR}\n")

    with sync_playwright() as pw:
        # Launch headless Chromium browser
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            device_scale_factor=DEVICE_SCALE,
        )
        page = context.new_page()

        rendered = 0
        for case in cases:
            case_id = case["id"]
            rail = case["visible"]["rail"]
            print(f"  [{case_id}] {case['title'][:60]}... ({rail})")

            out_path = render_case(page, case, OUTPUT_DIR)
            if out_path:
                rendered += 1
                print(f"         → {out_path.name} ✓")

        browser.close()

    print(f"\n✓ Rendered {rendered}/{len(cases)} images to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
