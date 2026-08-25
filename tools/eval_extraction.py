"""Extraction Accuracy Evaluator (`proofpay-demo report`).

Evaluates the extraction pipeline across all demo receipt cases in manifest.json,
comparing extracted PaymentClaim fields against visual ground truth.

Computes:
  - n: Total evaluated cases
  - correct: Extracted value matches ground truth exactly
  - null: Value was null / unreadable (safe abstention)
  - WRONG: Extracted value was non-null but incorrect
  - acc: correct / n (%)
  - dangerous: WRONG / n (%)  [Target: dangerous == 0% on amount & reference_id]

Outputs a markdown report to fixtures/demo/extraction_accuracy.md.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add backend to path so proofpay imports work when run from repo root
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from typing import Any

from proofpay.extraction.service import ExtractionService

MANIFEST_PATH = REPO_ROOT / "fixtures" / "demo" / "manifest.json"
REPORT_OUTPUT_PATH = REPO_ROOT / "fixtures" / "demo" / "extraction_accuracy.md"


def evaluate_extraction(mode: str = "auto") -> dict[str, Any]:
    """Run extraction evaluation on all manifest cases."""
    if not MANIFEST_PATH.exists():
        print(f"Error: Manifest not found at {MANIFEST_PATH}")
        sys.exit(1)

    with open(MANIFEST_PATH, encoding="utf-8") as f:
        manifest = json.load(f)

    cases = manifest.get("cases", [])
    service = ExtractionService(mode=mode)

    results = {
        "amount": {"n": 0, "correct": 0, "null": 0, "wrong": 0},
        "reference_id": {"n": 0, "correct": 0, "null": 0, "wrong": 0},
        "sender_name": {"n": 0, "correct": 0, "null": 0, "wrong": 0},
        "receiver_name": {"n": 0, "correct": 0, "null": 0, "wrong": 0},
        "provider": {"n": 0, "correct": 0, "null": 0, "wrong": 0},
    }

    print(f"Evaluating extraction on {len(cases)} manifest cases (mode={mode})...")

    for case in cases:
        case_id = case["id"]
        rel_img = case.get("images", {}).get("delivered") if case.get("images") else f"images/{case_id}.jpg"

        img_path = REPO_ROOT / "fixtures" / "demo" / rel_img
        if not img_path.exists():
            print(f"Skipping {case_id}: image not found at {img_path}")
            continue

        raw_bytes = img_path.read_bytes()
        claim = service.extract(raw_bytes, claim_id=f"eval-{case_id}")
        vis = case.get("visible", {})

        # 1. Amount
        results["amount"]["n"] += 1
        expected_paisa = vis.get("amount_paisa")

        if claim.amount is None:
            results["amount"]["null"] += 1
        elif expected_paisa is not None and claim.amount.minor == expected_paisa:
            results["amount"]["correct"] += 1
        else:
            results["amount"]["wrong"] += 1

        # 2. Reference ID
        results["reference_id"]["n"] += 1
        expected_ref = vis.get("reference_id")
        if claim.reference_id is None:
            results["reference_id"]["null"] += 1
        elif expected_ref and claim.reference_id.strip() == expected_ref.strip():
            results["reference_id"]["correct"] += 1
        else:
            results["reference_id"]["wrong"] += 1

        # 3. Sender Name
        results["sender_name"]["n"] += 1
        expected_sender = vis.get("sender_name")
        if claim.sender_name is None:
            results["sender_name"]["null"] += 1
        elif expected_sender and _name_matches(claim.sender_name, expected_sender):
            results["sender_name"]["correct"] += 1
        else:
            results["sender_name"]["wrong"] += 1

        # 4. Receiver Name
        results["receiver_name"]["n"] += 1
        expected_rec = vis.get("receiver_name")
        if claim.receiver_name is None:
            results["receiver_name"]["null"] += 1
        elif expected_rec and _name_matches(claim.receiver_name, expected_rec):
            results["receiver_name"]["correct"] += 1
        else:
            results["receiver_name"]["wrong"] += 1

        # 5. Provider
        results["provider"]["n"] += 1
        expected_prov = vis.get("rail")
        if claim.provider is None:
            results["provider"]["null"] += 1
        elif expected_prov and claim.provider.lower() == expected_prov.lower():
            results["provider"]["correct"] += 1
        else:
            results["provider"]["wrong"] += 1

    _write_report(results, mode)
    return results


def _name_matches(a: str, b: str) -> bool:
    """Loose comparison for names ignoring case and excess whitespace."""
    norm = lambda s: " ".join(s.lower().split())
    return norm(a) == norm(b) or norm(a) in norm(b) or norm(b) in norm(a)


def _write_report(results: dict[str, dict[str, int]], mode: str) -> None:
    """Format and save markdown evaluation report."""
    lines = [
        "# ProofPay Receipt Extraction Accuracy Report",
        "",
        f"**Mode**: `{mode}` | **Evaluated Cases**: {results['amount']['n']}",
        "",
        "| Field | n | Correct | Null (Safe) | WRONG | Accuracy | Dangerous % |",
        "|---|---|---|---|---|---|---|",
    ]

    for field, stats in results.items():
        n = stats["n"]
        if n == 0:
            continue
        corr = stats["correct"]
        null_c = stats["null"]
        wrong = stats["wrong"]
        acc = (corr / n) * 100
        dang = (wrong / n) * 100
        lines.append(
            f"| `{field}` | {n} | {corr} | {null_c} | {wrong} | {acc:.1f}% | **{dang:.1f}%** |"
        )

    lines.extend([
        "",
        "> [!IMPORTANT]",
        "> **Dangerous %** measures non-null incorrect extractions.",
        "> ProofPay target: `dangerous == 0.0%` for `amount` and `reference_id`.",
        "> A safe abstention (null) routes to `NEEDS_REVIEW` rather than risking a false `VERIFIED`.",
    ])

    report_content = "\n".join(lines)
    # newline="\n": `write_text` uses the platform default, which on Windows
    # rewrites all 15 line endings to CRLF and reports the whole committed
    # report as modified even when every number is unchanged.
    REPORT_OUTPUT_PATH.write_text(report_content, encoding="utf-8", newline="\n")
    print(f"\n{report_content}\n")
    print(f"Report saved to {REPORT_OUTPUT_PATH}")


if __name__ == "__main__":
    # Defaults to "offline", not "auto", because this writes a COMMITTED file.
    # With no API key present "auto" produces byte-identical accuracy numbers
    # but stamps `Mode: auto` in the header, so running the tool to check the
    # report silently dirties the working tree and makes it look as though
    # something regressed. Ask for "auto" or "cloud" explicitly to hit Qwen-VL.
    mode_arg = sys.argv[1] if len(sys.argv) > 1 else "offline"
    evaluate_extraction(mode_arg)
