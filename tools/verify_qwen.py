"""Prove the Qwen-VL path works, and that it does not move the demo.

Run from the repo root, once a DashScope key is in `backend/.env`:

    cd backend && uv run python ../tools/verify_qwen.py

WHY THIS EXISTS SEPARATELY FROM `eval_extraction.py`

`tools/eval_extraction.py cloud` already measures FIELD accuracy against the
manifest's ground truth, which is the right thing for it to measure. It cannot
answer the two questions that decide whether the demo may be switched to the
cloud reader on the day:

  1. Am I actually talking to Qwen?  `Settings.effective_receipt_extractor()`
     falls back to "deterministic" when the key is missing, and the fallback is
     SILENT by design, so that a missing credential degrades the product instead
     of breaking it. The cost of that kindness is that a misspelt variable looks
     exactly like a successful cloud run. This script refuses to continue unless
     the object about to be called is really the DashScope adapter.

  2. Does the cloud reader change the VERDICT?  Field accuracy and verdict
     agreement are different things: a receipt can lose a field and still verify,
     or read perfectly and still route to review. The demo shows five verdicts,
     so five verdicts are what has to be checked.

Nothing here is a substitute for `eval_extraction.py`; run both.

WHAT IT COSTS

One model call per demo case, five in total. The adapter does not surface token
usage, so this script cannot report quota consumption. Read that from the Model
Studio console; the free quota is per model, and five receipts is a rounding
error against it.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from dataclasses import replace
from datetime import UTC

from proofpay.api.engine_demo import demo_case_for
from proofpay.config import get_settings
from proofpay.core.decide import DecisionPolicy, decide
from proofpay.demo.clock import PINNED_ANCHOR
from proofpay.extraction.service import ExtractionService

IMAGES = REPO_ROOT / "fixtures" / "demo" / "images"

#: The demo merchant. `demo_case_for` scopes its case to a merchant so the engine
#: sees a tenant-consistent ledger; the id only has to be stable, not real.
MERCHANT = "merchant_demo_001"

#: The five the demo tells, in the order it tells them. Order id, receipt, and
#: the verdict the deterministic path is already known to produce.
DEMO = [
    ("order_demo_1001", "G01.jpg", "VERIFIED"),
    ("order_demo_1002", "S01.jpg", "SUSPICIOUS"),
    ("order_demo_1003", "D01.jpg", "DUPLICATE"),
    ("order_demo_1004", "N01.jpg", "NEEDS_REVIEW"),
    ("order_demo_1005", "U01.jpg", "UNMATCHED"),
]


def preflight() -> str:
    """Refuse to run unless the cloud adapter is genuinely what we will call.

    Returns the model name. Raises SystemExit with something actionable rather
    than a traceback, because the likely reader of a failure here is whoever has
    just created their first API key.
    """
    settings = get_settings()

    if not settings.dashscope_api_key:
        raise SystemExit(
            "No API key.\n"
            "  Put PROOFPAY_DASHSCOPE_API_KEY=... in backend/.env and run again.\n"
            "  The file is gitignored; do not commit it."
        )

    effective = settings.effective_receipt_extractor()
    if effective != "qwen":
        raise SystemExit(
            f"A key is set but the effective extractor is {effective!r}.\n"
            "  Set PROOFPAY_RECEIPT_EXTRACTOR=qwen in backend/.env.\n"
            "  Note the PROOFPAY_ prefix; without it the setting is ignored."
        )

    service = ExtractionService(
        api_key=settings.dashscope_api_key, mode="cloud", model=settings.qwen_model
    )
    extractor = service.extractor
    name = type(extractor).__name__
    if name != "DashScopeOcrExtractor":
        raise SystemExit(
            f"Expected the DashScope adapter, got {name}.\n"
            "  Something is still routing to the offline stub."
        )

    return getattr(extractor, "model", "(unknown)")


def verdict_for(order_id: str, image_name: str, service: ExtractionService) -> tuple[str, str]:
    """Run one receipt through this extractor and the real engine.

    `claim_id` is the MANIFEST CASE ID ("G01"), not the order id, and that is
    what the API passes too. The offline stub matches on the sha256 of the bytes
    it is handed, but `ExtractionService.extract` downscales first, so the hash
    no longer matches the committed original; the case id is the stub's second
    lookup and the only one that survives preprocessing. The cloud adapter
    ignores the argument entirely, so both sides can be driven identically.
    """
    case = demo_case_for(order_id, MERCHANT)
    content = (IMAGES / image_name).read_bytes()
    case_id = Path(image_name).stem

    claim = service.extract(content, claim_id=case_id)
    claim = replace(claim, merchant_id=MERCHANT, proof_id=order_id)

    decision = decide(
        claim,
        case.order,
        case.ledger,
        case.allocations,
        now=PINNED_ANCHOR.astimezone(UTC),
        policy=DecisionPolicy(),
    )
    return decision.status.value, decision.fired_rule_id


def main() -> int:
    model = preflight()
    print(f"Talking to DashScope. Model: {model}\n")

    cloud = ExtractionService(
        api_key=get_settings().dashscope_api_key, mode="cloud", model=get_settings().qwen_model
    )
    offline = ExtractionService(mode="offline")

    print(f"{'order':17} {'receipt':9} {'deterministic':22} {'qwen-vl':22} agree")
    print("-" * 82)

    disagreements = 0
    failures = 0
    for order_id, image_name, _known in DEMO:
        try:
            off_status, off_rule = verdict_for(order_id, image_name, offline)
        # Blind catch on purpose: this is a diagnostic, and its job is to tell
        # you what went wrong with EACH case rather than abort on the first.
        except Exception as exc:  # noqa: BLE001
            print(f"{order_id:17} {image_name:9} OFFLINE FAILED: {exc}")
            failures += 1
            continue

        try:
            qwen_status, qwen_rule = verdict_for(order_id, image_name, cloud)
        # Same reasoning: a rate limit on case three should not hide cases four
        # and five, which are the ones that tell you whether it is systemic.
        except Exception as exc:  # noqa: BLE001
            print(f"{order_id:17} {image_name:9} {off_status + '/' + off_rule:22} CALL FAILED: {exc}")
            failures += 1
            continue

        agree = off_status == qwen_status
        if not agree:
            disagreements += 1
        print(
            f"{order_id:17} {image_name:9} "
            f"{off_status + '/' + off_rule:22} {qwen_status + '/' + qwen_rule:22} "
            f"{'yes' if agree else 'NO'}"
        )

    print()
    if failures:
        print(f"{failures} case(s) could not be evaluated. Fix those before reading the rest.")
        return 2
    if disagreements:
        print(
            f"{disagreements} of {len(DEMO)} verdicts CHANGE under Qwen-VL.\n"
            "The demo is currently rehearsed on the deterministic path, so switching\n"
            "would change what the room sees. Decide deliberately; do not switch on\n"
            "the day."
        )
        return 1

    print(
        f"All {len(DEMO)} verdicts match the deterministic path.\n"
        "The cloud reader can be demonstrated without changing what the room sees.\n"
        "For field-level accuracy, run: uv run python ../tools/eval_extraction.py cloud"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
