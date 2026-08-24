"""Manifest Authoring Script — Generates fixtures/demo/manifest.json.

WHY THIS FILE EXISTS:
    manifest.json is the single source of truth for the entire ProofPay demo dataset.
    It contains 30 fixture cases driving:
      - Unit & contract tests (Track A Engine & Track C Extractor)
      - Image generation & tampering (Track C Render Pipeline)
      - Database seeding (Track B & Track C Seeder)
      - Ground-truth accuracy reporting

    Writing 1,200 lines of JSON manually is error-prone. This script programmatically
    constructs every case using `tools/pk_data.py` and `proofpay.demo.clock`,
    validates schema consistency, and outputs `fixtures/demo/manifest.json`.

DATA MODEL PER CASE:
    - id:          Unique case identifier (G01–G10, U01–U04, S01–S06, D01–D04, N01–N06)
    - title:       Human-readable description of scenario
    - category:    VERIFIED | UNMATCHED | SUSPICIOUS | DUPLICATE | NEEDS_REVIEW
    - tamper_type: Forensic artifact to inject (SUSPICIOUS cases only)
    - visible:     Screenshot visual ground truth (what OCR should extract)
    - ledger:      LIST of merchant trusted feed rows (what actually happened).
                   A list because a real feed can hold two transfers a receipt
                   cannot tell apart — N03 is exactly that case, and a single
                   object cannot express it. Empty list = nothing in the feed.
                   `status` is load-bearing, not decorative: core's LedgerTxn has
                   no status field, so only POSTED rows may be handed to the
                   engine. U02 is an in-flight payment and must stay PENDING.
    - allocations: LIST of earlier claims that already consumed a transaction.
                   Present (usually empty) on every case so no reader concludes
                   a case predates the feature. Each entry is:
                     external_transaction_id — joins to a row in THIS case's
                       ledger; spelled the same as the ledger key so the join is
                       visible by eye. Becomes Allocation.txn_id, and the
                       identity LedgerTxn.txn_id == Allocation.txn_id is what
                       the engine's duplicate rule actually tests.
                     allocated_to_order_ref — the EARLIER order holding the
                       payment. Must differ from this case's own
                       order.external_order_ref: core reads an allocation naming
                       the same order as idempotent re-verification and lets the
                       claim through, which silently un-does the whole scenario.
                     allocated_offset_min — optional, minutes from the pinned
                       anchor. Core orders contested allocations by this.
                   Deliberately omitted: `verification_id` (core accepts None
                   and nothing reads it) and an ACTIVE/RELEASED `status` (no
                   case needs a released allocation yet, and an unconsumed key
                   is how ledger.status sat decorative for months).
    - order:       Expected order details (what customer ordered)
    - expected:    Expected verification decision & reason code
    - images:      Hash of the committed receipt JPEG (see `_image_meta`). Absent
                   only on a case bootstrapped with --allow-missing-images, i.e.
                   one whose receipt has not been rendered yet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# Add backend to path for clock imports
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from pk_data import (
    demo_txn_ref,
)


def _image_meta(case_id: str, *, allow_missing: bool = False) -> dict | None:
    """Hash the committed receipt JPEG so the manifest is genuinely self-generating.

    This block used to be bolted on by tools/hash_images.py after the fact, so
    re-running this script silently stripped `images` from every case and left
    the extractor unable to find a single fixture (it resolves an upload by
    sha256, and the API rejects any image it cannot map to a case). The images
    themselves are committed and are never regenerated here — rendering them
    needs Playwright and does not reproduce byte-for-byte across font and JPEG
    encoder versions. This only records what is already on disk, and raises on
    a missing file rather than emitting a manifest the extractor cannot use.

    `allow_missing` exists to break a bootstrap deadlock, and for nothing else.
    tools/render_receipts.py renders images BY READING manifest.json, so a case
    that has never been rendered cannot be added at all while this function is
    unconditionally fatal: the manifest will not build without the image, and
    the image will not render without the manifest. With the flag set, the case
    is emitted with NO `images` key at all — deliberately absent rather than
    null, because `verifications._fixture_case_ids` does
    `case.get("images", {}).get("sha256")`, which a null value turns into an
    AttributeError while an absent key falls through harmlessly. Returning None
    here means "omit"; see the caller.
    """
    image_path = REPO_ROOT / "fixtures" / "demo" / "images" / f"{case_id}.jpg"
    if not image_path.exists():
        if allow_missing:
            print(
                f"  WARNING {case_id}: no receipt image at {image_path}. Emitting the "
                f"case with no `images` block. This manifest is a BOOTSTRAP ONLY: run "
                f"tools/render_receipts.py --case {case_id}, then tools/tamper_receipts.py, "
                f"then rebuild WITHOUT --allow-missing-images before committing."
            )
            return None
        raise FileNotFoundError(
            f"{case_id}: no receipt image at {image_path}. The images are committed "
            f"fixtures; regenerate them with tools/render_receipts.py before rebuilding. "
            f"If this is a BRAND NEW case that has never been rendered, render_receipts "
            f"cannot see it until it is in the manifest: rebuild once with "
            f"--allow-missing-images, render, then rebuild again without the flag."
        )

    payload = image_path.read_bytes()
    return {
        "delivered": f"images/{case_id}.jpg",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
    }


def generate_manifest(*, allow_missing_images: bool = False) -> dict:
    """Build the complete 30-case demo manifest data structure.

    `allow_missing_images` is forwarded to `_image_meta` and is only ever set
    when bootstrapping a case whose receipt has not been rendered yet.
    """

    cases = []

    # Common receiver for all demo transactions
    MERCHANT_RECEIVER = "Ali Traders"

    # ═════════════════════════════════════════════════════════════════
    # 1. VERIFIED CASES (G01–G10) — 10 Clean & Normal Variations
    # ═════════════════════════════════════════════════════════════════

    # G01: Perfect Exact Match (Easypaisa)
    cases.append({
        "id": "G01",
        "title": "Exact match — Easypaisa wallet transfer",
        "category": "VERIFIED",
        "visible": {
            "rail": "easypaisa",
            "amount_paisa": 150000,  # PKR 1,500.00
            "reference_id": demo_txn_ref("easypaisa", 1),
            "sender_name": "Bilal Ahmed Khan",
            "receiver_name": MERCHANT_RECEIVER,
            "claimed_offset_min": -11,
            "raw_timestamp_text": "20 Aug 2026, 01:54 PM",
        },
        "ledger": [
            {
                "rail": "easypaisa",
                "amount_paisa": 150000,
                "external_transaction_id": demo_txn_ref("easypaisa", 1),
                "sender_name": "Bilal Ahmed Khan",
                "receiver_name": MERCHANT_RECEIVER,
                "ledger_offset_min": -12,
                "status": "POSTED",
                "trust_level": "SIMULATOR",
            },
        ],
        "allocations": [],
        "order": {
            "external_order_ref": "ORD-G01",
            "expected_amount_paisa": 150000,
        },
        "expected": {
            "outcome": "VERIFIED",
            "reason_code": "STRONG_FIELD_AGREEMENT",
        },
    })

    # G02: Transliteration Variant (Muhammad ↔ Mohammad)
    cases.append({
        "id": "G02",
        "title": "Fuzzy sender match — Transliteration variant (Muhammad / Mohammad)",
        "category": "VERIFIED",
        "visible": {
            "rail": "jazzcash",
            "amount_paisa": 250000,  # PKR 2,500.00
            "reference_id": demo_txn_ref("jazzcash", 2),
            "sender_name": "Muhammad Usman Sheikh",
            "receiver_name": MERCHANT_RECEIVER,
            "claimed_offset_min": -20,
            "raw_timestamp_text": "20 Aug 2026, 01:45 PM",
        },
        "ledger": [
            {
                "rail": "jazzcash",
                "amount_paisa": 250000,
                "external_transaction_id": demo_txn_ref("jazzcash", 2),
                "sender_name": "Mohammad Usman Shaikh",  # Transliteration difference
                "receiver_name": MERCHANT_RECEIVER,
                "ledger_offset_min": -21,
                "status": "POSTED",
                "trust_level": "SIMULATOR",
            },
        ],
        "allocations": [],
        "order": {
            "external_order_ref": "ORD-G02",
            "expected_amount_paisa": 250000,
        },
        "expected": {
            "outcome": "VERIFIED",
            "reason_code": "STRONG_FIELD_AGREEMENT",
        },
    })

    # G03–G10: Remaining VERIFIED cases covering different rails and variations
    rails_distribution = [
        ("G03", "raast", "Raast P2P transfer — exact match", 350000, "Saad Tariq Qureshi"),
        ("G04", "bank", "Bank IBFT transfer — exact match", 500000, "Faisal Javed Malik"),
        ("G05", "easypaisa", "Overpayment accepted — paid 2,000 for 1,500 order", 200000, "Hassan Raza Shah"),
        ("G06", "jazzcash", "Minor 5-min timestamp drift between receipt and ledger", 180000, "Hamza Imran Butt"),
        ("G07", "raast", "Initials match (M B Shaikh vs Muhammad Bilal Shaikh)", 420000, "M B Shaikh"),
        ("G08", "bank", "Whitespace and case variation in sender name", 300000, "KASHIF ALTAF KHAN"),
        ("G09", "easypaisa", "Easypaisa store transfer — exact match", 85000, "Ayesha Fatima"),
        ("G10", "jazzcash", "JazzCash merchant QR payment", 120000, "Omar Farooq"),
    ]

    for idx, (cid, rail, title, amt, sender) in enumerate(rails_distribution, start=3):
        order_amt = 150000 if cid == "G05" else amt  # G05 is overpayment (paid 2000, expected 1500)
        cases.append({
            "id": cid,
            "title": title,
            "category": "VERIFIED",
            "visible": {
                "rail": rail,
                "amount_paisa": amt,
                "reference_id": demo_txn_ref(rail, idx),
                "sender_name": sender,
                "receiver_name": MERCHANT_RECEIVER,
                "claimed_offset_min": -(idx * 5),
                "raw_timestamp_text": "20 Aug 2026",
            },
            "ledger": [
                {
                    "rail": rail,
                    "amount_paisa": amt,
                    "external_transaction_id": demo_txn_ref(rail, idx),
                    "sender_name": sender if cid != "G07" else "Muhammad Bilal Shaikh",
                    "receiver_name": MERCHANT_RECEIVER,
                    "ledger_offset_min": -(idx * 5 + 1),
                    "status": "POSTED",
                    "trust_level": "SIMULATOR",
                },
            ],
            "allocations": [],
            "order": {
                "external_order_ref": f"ORD-{cid}",
                "expected_amount_paisa": order_amt,
            },
            "expected": {
                "outcome": "VERIFIED",
                "reason_code": "STRONG_FIELD_AGREEMENT" if cid != "G05" else "AMOUNT_OVERPAID",
                },
        })

    # ═════════════════════════════════════════════════════════════════
    # 2. UNMATCHED CASES (U01–U04) — No Trusted Match in Ledger
    # ═════════════════════════════════════════════════════════════════

    cases.append({
        "id": "U01",
        "title": "Non-existent transaction ID — fake screenshot ref",
        "category": "UNMATCHED",
        "visible": {
            "rail": "easypaisa",
            "amount_paisa": 150000,
            "reference_id": "EP99999999",  # Does not exist in merchant feed
            "sender_name": "Tariq Mahmood",
            "receiver_name": MERCHANT_RECEIVER,
            "claimed_offset_min": -10,
            "raw_timestamp_text": "20 Aug 2026, 01:55 PM",
        },
        "ledger": [],  # No transaction in ledger at all!
        "allocations": [],
        "order": {
            "external_order_ref": "ORD-U01",
            "expected_amount_paisa": 150000,
        },
        "expected": {
            "outcome": "UNMATCHED",
            "reason_code": "NO_CANDIDATES",
        },
    })

    cases.append({
        "id": "U02",
        "title": "Pending settlement — payment in-flight, feed delayed",
        "category": "UNMATCHED",
        "visible": {
            "rail": "jazzcash",
            "amount_paisa": 200000,
            "reference_id": demo_txn_ref("jazzcash", 20),
            "sender_name": "Asad Ullah",
            "receiver_name": MERCHANT_RECEIVER,
            "claimed_offset_min": -2,
            "raw_timestamp_text": "20 Aug 2026, 02:03 PM",
        },
        "ledger": [
            {
                "rail": "jazzcash",
                "amount_paisa": 200000,
                "external_transaction_id": demo_txn_ref("jazzcash", 20),
                "sender_name": "Asad Ullah",
                "receiver_name": MERCHANT_RECEIVER,
                "ledger_offset_min": -2,
                "status": "PENDING",  # Not posted yet!
                "trust_level": "SIMULATOR",
            },
        ],
        "allocations": [],
        "order": {
            "external_order_ref": "ORD-U02",
            "expected_amount_paisa": 200000,
        },
        "expected": {
            "outcome": "UNMATCHED",
            "reason_code": "NO_CANDIDATES",
        },
    })

    cases.append({
        "id": "U03",
        "title": "Feed window expired — transfer occurred 5 days ago",
        "category": "UNMATCHED",
        "visible": {
            "rail": "raast",
            "amount_paisa": 150000,
            "reference_id": demo_txn_ref("raast", 21),
            "sender_name": "Kamran Akmal",
            "receiver_name": MERCHANT_RECEIVER,
            "claimed_offset_min": -7200,  # 5 days ago
            "raw_timestamp_text": "15 Aug 2026, 02:05 PM",
        },
        "ledger": [],
        "allocations": [],
        "order": {
            "external_order_ref": "ORD-U03",
            "expected_amount_paisa": 150000,
        },
        "expected": {
            "outcome": "UNMATCHED",
            "reason_code": "TIMESTAMP_MISMATCH",
        },
    })

    cases.append({
        "id": "U04",
        "title": "Wrong receiver account — money sent to wrong merchant",
        "category": "UNMATCHED",
        "visible": {
            "rail": "bank",
            "amount_paisa": 300000,
            "reference_id": demo_txn_ref("bank", 22),
            "sender_name": "Zubair Ahmed",
            "receiver_name": "Other Shop Electronics",  # Wrong merchant!
            "claimed_offset_min": -15,
            "raw_timestamp_text": "20 Aug 2026, 01:50 PM",
        },
        "ledger": [],
        "allocations": [],
        "order": {
            "external_order_ref": "ORD-U04",
            "expected_amount_paisa": 300000,
        },
        "expected": {
            "outcome": "UNMATCHED",
            "reason_code": "NAME_MISMATCH",
        },
    })

    # ═════════════════════════════════════════════════════════════════
    # 3. SUSPICIOUS CASES (S01–S06) — Tampered or Conflicting Claims
    # ═════════════════════════════════════════════════════════════════

    # S01: Inflated Amount Claim (Image shows 5,000 PKR, Ledger has 500 PKR)
    cases.append({
        "id": "S01",
        "title": "Claimed amount inflated — receipt edited from Rs 500 to Rs 5,000",
        "category": "SUSPICIOUS",
        "tamper_type": "amount_edit",
        "visible": {
            "rail": "easypaisa",
            "amount_paisa": 500000,  # 5,000 PKR (edited image claim)
            "reference_id": demo_txn_ref("easypaisa", 30),
            "sender_name": "Shoaib Malik",
            "receiver_name": MERCHANT_RECEIVER,
            "claimed_offset_min": -10,
            "raw_timestamp_text": "20 Aug 2026, 01:55 PM",
        },
        "ledger": [
            {
                "rail": "easypaisa",
                "amount_paisa": 50000,   # 500 PKR (real ledger value)
                "external_transaction_id": demo_txn_ref("easypaisa", 30),
                "sender_name": "Shoaib Malik",
                "receiver_name": MERCHANT_RECEIVER,
                "ledger_offset_min": -11,
                "status": "POSTED",
                "trust_level": "SIMULATOR",
            },
        ],
        "allocations": [],
        "order": {
            "external_order_ref": "ORD-S01",
            "expected_amount_paisa": 500000,
        },
        "expected": {
            "outcome": "SUSPICIOUS",
            "reason_code": "CLAIM_INFLATED",
        },
    })

    # S02: Reference ID Altered in Pixels
    cases.append({
        "id": "S02",
        "title": "Altered transaction ref — last digits edited in screenshot",
        "category": "SUSPICIOUS",
        "tamper_type": "ref_edit",
        "visible": {
            "rail": "jazzcash",
            "amount_paisa": 150000,
            "reference_id": "JC0000319",  # Edited TID on image
            "sender_name": "Waseem Akram",
            "receiver_name": MERCHANT_RECEIVER,
            "claimed_offset_min": -15,
            "raw_timestamp_text": "20 Aug 2026, 01:50 PM",
        },
        "ledger": [
            {
                "rail": "jazzcash",
                "amount_paisa": 150000,
                "external_transaction_id": "JC0000311",  # Real TID in ledger
                "sender_name": "Waseem Akram",
                "receiver_name": MERCHANT_RECEIVER,
                "ledger_offset_min": -16,
                "status": "POSTED",
                "trust_level": "SIMULATOR",
            },
        ],
        "allocations": [],
        "order": {
            "external_order_ref": "ORD-S02",
            "expected_amount_paisa": 150000,
        },
        "expected": {
            "outcome": "SUSPICIOUS",
            "reason_code": "REFERENCE_MISMATCH",
        },
    })

    # S03–S06: Other Tamper Scenarios
    suspicious_variants = [
        ("S03", "date_edit", "Timestamp edited — date changed to match today's order", 200000, "Rizwan Ahmed"),
        ("S04", "name_edit", "Sender name replaced — someone else's receipt edited", 150000, "Adeel Chaudhry"),
        ("S05", "fabricated", "Fabricated receipt — entirely generated fake image", 350000, "Fake Customer"),
        ("S06", "careful_edit", "Careful edit with no forensic trace — caught by ledger alone", 180000, "Naveed Iqbal"),
    ]

    for cid, ttype, title, amt, sender in suspicious_variants:
        cases.append({
            "id": cid,
            "title": title,
            "category": "SUSPICIOUS",
            "tamper_type": ttype,
            "visible": {
                "rail": "easypaisa",
                "amount_paisa": amt * 2,  # Image shows double
                "reference_id": f"EP{cid}999",
                "sender_name": sender,
                "receiver_name": MERCHANT_RECEIVER,
                "claimed_offset_min": -10,
                "raw_timestamp_text": "20 Aug 2026, 01:55 PM",
            },
            "ledger": [
                {
                    "rail": "easypaisa",
                    "amount_paisa": amt,
                    "external_transaction_id": f"EP{cid}999",
                    "sender_name": sender,
                    "receiver_name": MERCHANT_RECEIVER,
                    "ledger_offset_min": -11,
                    "status": "POSTED",
                    "trust_level": "SIMULATOR",
                },
            ],
            "allocations": [],
            "order": {
                "external_order_ref": f"ORD-{cid}",
                "expected_amount_paisa": amt * 2,
            },
            "expected": {
                "outcome": "SUSPICIOUS",
                "reason_code": "FIELD_CONTRADICTS_MATCH",
                },
        })

    # ═════════════════════════════════════════════════════════════════
    # 4. DUPLICATE CASES (D01–D04) — Reused Transactions or Images
    # ═════════════════════════════════════════════════════════════════

    cases.append({
        "id": "D01",
        "title": "Transaction already consumed — assigned to previous order",
        "category": "DUPLICATE",
        "visible": {
            "rail": "easypaisa",
            "amount_paisa": 150000,
            "reference_id": demo_txn_ref("easypaisa", 1),  # Same TID as G01!
            "sender_name": "Bilal Ahmed Khan",
            "receiver_name": MERCHANT_RECEIVER,
            "claimed_offset_min": -11,
            "raw_timestamp_text": "20 Aug 2026, 01:54 PM",
        },
        "ledger": [
            {
                "rail": "easypaisa",
                "amount_paisa": 150000,
                "external_transaction_id": demo_txn_ref("easypaisa", 1),
                "sender_name": "Bilal Ahmed Khan",
                "receiver_name": MERCHANT_RECEIVER,
                "ledger_offset_min": -12,
                "status": "POSTED",
                "trust_level": "SIMULATOR",
            },
        ],
        # G01 already consumed this exact transaction. R020 fires on the
        # allocation, not on the image: without a record of the earlier claim
        # the engine can only answer VERIFIED, which is how a rider gets paid
        # twice for one transfer.
        "allocations": [
            {
                "external_transaction_id": demo_txn_ref("easypaisa", 1),
                "allocated_to_order_ref": "ORD-G01",
                "allocated_offset_min": -11,
            },
        ],
        "order": {
            "external_order_ref": "ORD-D01",  # Second order trying to claim G01's payment
            "expected_amount_paisa": 150000,
        },
        "expected": {
            "outcome": "DUPLICATE",
            "reason_code": "TXN_ALREADY_ALLOCATED",
        },
    })

    cases.append({
        "id": "D02",
        "title": "Exact SHA-256 screenshot reuse — identical image submitted twice",
        "category": "DUPLICATE",
        "visible": {
            "rail": "jazzcash",
            "amount_paisa": 250000,
            "reference_id": demo_txn_ref("jazzcash", 2),
            "sender_name": "Muhammad Usman Sheikh",
            "receiver_name": MERCHANT_RECEIVER,
            "claimed_offset_min": -20,
            "raw_timestamp_text": "20 Aug 2026, 01:45 PM",
        },
        "ledger": [
            {
                "rail": "jazzcash",
                "amount_paisa": 250000,
                "external_transaction_id": demo_txn_ref("jazzcash", 2),
                "sender_name": "Muhammad Usman Sheikh",
                "receiver_name": MERCHANT_RECEIVER,
                "ledger_offset_min": -21,
                "status": "POSTED",
                "trust_level": "SIMULATOR",
            },
        ],
        "allocations": [],
        "order": {
            "external_order_ref": "ORD-D02",
            "expected_amount_paisa": 250000,
        },
        "expected": {
            "outcome": "DUPLICATE",
            "reason_code": "PROOF_REUSED",
        },
    })

    cases.append({
        "id": "D03",
        "title": "Perceptual pHash screenshot reuse — cropped variant of previous proof",
        "category": "DUPLICATE",
        "visible": {
            "rail": "raast",
            "amount_paisa": 350000,
            "reference_id": demo_txn_ref("raast", 3),
            "sender_name": "Saad Tariq Qureshi",
            "receiver_name": MERCHANT_RECEIVER,
            "claimed_offset_min": -15,
            "raw_timestamp_text": "20 Aug 2026, 01:50 PM",
        },
        "ledger": [
            {
                "rail": "raast",
                "amount_paisa": 350000,
                "external_transaction_id": demo_txn_ref("raast", 3),
                "sender_name": "Saad Tariq Qureshi",
                "receiver_name": MERCHANT_RECEIVER,
                "ledger_offset_min": -16,
                "status": "POSTED",
                "trust_level": "SIMULATOR",
            },
        ],
        "allocations": [],
        "order": {
            "external_order_ref": "ORD-D03",
            "expected_amount_paisa": 350000,
        },
        "expected": {
            "outcome": "DUPLICATE",
            "reason_code": "PROOF_REUSED",
        },
    })

    cases.append({
        "id": "D04",
        "title": "Cross-order double claim — rider re-submitting proof from Order #1",
        "category": "DUPLICATE",
        "visible": {
            "rail": "bank",
            "amount_paisa": 500000,
            "reference_id": demo_txn_ref("bank", 4),
            "sender_name": "Faisal Javed Malik",
            "receiver_name": MERCHANT_RECEIVER,
            "claimed_offset_min": -20,
            "raw_timestamp_text": "20 Aug 2026, 01:45 PM",
        },
        "ledger": [
            {
                "rail": "bank",
                "amount_paisa": 500000,
                "external_transaction_id": demo_txn_ref("bank", 4),
                "sender_name": "Faisal Javed Malik",
                "receiver_name": MERCHANT_RECEIVER,
                "ledger_offset_min": -21,
                "status": "POSTED",
                "trust_level": "SIMULATOR",
            },
        ],
        # The rider is re-submitting Order #1's proof. ORD-G04 holds this
        # transaction already; the order refs must differ or core reads the
        # allocation as an idempotent re-verification and lets it through.
        "allocations": [
            {
                "external_transaction_id": demo_txn_ref("bank", 4),
                "allocated_to_order_ref": "ORD-G04",
                "allocated_offset_min": -20,
            },
        ],
        "order": {
            "external_order_ref": "ORD-D04",
            "expected_amount_paisa": 500000,
        },
        "expected": {
            "outcome": "DUPLICATE",
            "reason_code": "TXN_ALREADY_ALLOCATED",
        },
    })

    # ═════════════════════════════════════════════════════════════════
    # 5. NEEDS_REVIEW CASES (N01–N06) — Ambiguity or Incomplete Details
    # ═════════════════════════════════════════════════════════════════

    # N01: Underpaid Order (Paid 1,200 PKR for a 1,500 PKR order)
    cases.append({
        "id": "N01",
        "title": "Underpaid order — paid Rs 1,200 for Rs 1,500 order",
        "category": "NEEDS_REVIEW",
        "visible": {
            "rail": "easypaisa",
            "amount_paisa": 120000,  # 1,200 PKR paid
            "reference_id": demo_txn_ref("easypaisa", 50),
            "sender_name": "Waqar Younis",
            "receiver_name": MERCHANT_RECEIVER,
            "claimed_offset_min": -10,
            "raw_timestamp_text": "20 Aug 2026, 01:55 PM",
        },
        "ledger": [
            {
                "rail": "easypaisa",
                "amount_paisa": 120000,  # 1,200 PKR arrived
                "external_transaction_id": demo_txn_ref("easypaisa", 50),
                "sender_name": "Waqar Younis",
                "receiver_name": MERCHANT_RECEIVER,
                "ledger_offset_min": -11,
                "status": "POSTED",
                "trust_level": "SIMULATOR",
            },
        ],
        "allocations": [],
        "order": {
            "external_order_ref": "ORD-N01",
            "expected_amount_paisa": 150000,  # Expected 1,500 PKR
        },
        "expected": {
            "outcome": "NEEDS_REVIEW",
            "reason_code": "AMOUNT_UNDERPAID",
        },
    })

    # N02: Overpaid Review Required
    cases.append({
        "id": "N02",
        "title": "Overpaid order requires manager review — paid Rs 5,000 for Rs 1,500 order",
        "category": "NEEDS_REVIEW",
        "visible": {
            "rail": "jazzcash",
            "amount_paisa": 500000,
            "reference_id": demo_txn_ref("jazzcash", 51),
            "sender_name": "Junaid Jamshed",
            "receiver_name": MERCHANT_RECEIVER,
            "claimed_offset_min": -12,
            "raw_timestamp_text": "20 Aug 2026, 01:53 PM",
        },
        "ledger": [
            {
                "rail": "jazzcash",
                "amount_paisa": 500000,
                "external_transaction_id": demo_txn_ref("jazzcash", 51),
                "sender_name": "Junaid Jamshed",
                "receiver_name": MERCHANT_RECEIVER,
                "ledger_offset_min": -13,
                "status": "POSTED",
                "trust_level": "SIMULATOR",
            },
        ],
        "allocations": [],
        "order": {
            "external_order_ref": "ORD-N02",
            "expected_amount_paisa": 150000,
        },
        "expected": {
            "outcome": "NEEDS_REVIEW",
            "reason_code": "AMOUNT_OVERPAID",
        },
    })

    # N03: Ambiguous Candidates (Multiple ledger txns match amount & time)
    cases.append({
        "id": "N03",
        "title": "Ambiguous candidates — two identical PKR 1,500 transfers at same minute",
        "category": "NEEDS_REVIEW",
        "visible": {
            "rail": "easypaisa",
            "amount_paisa": 150000,
            "reference_id": None,  # Reference unreadable on blurred image
            "sender_name": "Irfan Khan",
            "receiver_name": MERCHANT_RECEIVER,
            "claimed_offset_min": -15,
            "raw_timestamp_text": "20 Aug 2026, 01:50 PM",
        },
        "ledger": [
            {
                "rail": "easypaisa",
                "amount_paisa": 150000,
                "external_transaction_id": demo_txn_ref("easypaisa", 52),
                "sender_name": "Irfan Khan",
                "receiver_name": MERCHANT_RECEIVER,
                "ledger_offset_min": -15,
                "status": "POSTED",
                "trust_level": "SIMULATOR",
            },
            {
                # The twin. Identical in every scored field: same amount, same
                # sender, same minute. Only the transaction id differs, because
                # a feed cannot carry one id twice — and because `visible`'s
                # reference_id is null, nothing on the receipt can tell the two
                # apart. That is the whole case: the engine must decline to
                # guess rather than pick the first row.
                "rail": "easypaisa",
                "amount_paisa": 150000,
                "external_transaction_id": demo_txn_ref("easypaisa", 53),
                "sender_name": "Irfan Khan",
                "receiver_name": MERCHANT_RECEIVER,
                "ledger_offset_min": -15,
                "status": "POSTED",
                "trust_level": "SIMULATOR",
            },
        ],
        "allocations": [],
        "order": {
            "external_order_ref": "ORD-N03",
            "expected_amount_paisa": 150000,
        },
        "expected": {
            "outcome": "NEEDS_REVIEW",
            "reason_code": "AMBIGUOUS_CANDIDATES",
        },
    })

    # N04–N06: Low OCR Confidence / Missing Timestamp / Cropped Receipt
    needs_review_variants = [
        ("N04", "Low OCR extraction confidence — image blurry", 150000, "Arslan Ash"),
        ("N05", "Missing timestamp on receipt screenshot", 250000, "Danish Taimoor"),
        ("N06", "Cropped receipt — sender name cut off", 180000, "Shahid Afridi"),
    ]

    for cid, title, amt, sender in needs_review_variants:
        cases.append({
            "id": cid,
            "title": title,
            "category": "NEEDS_REVIEW",
            "visible": {
                "rail": "jazzcash",
                "amount_paisa": amt,
                "reference_id": demo_txn_ref("jazzcash", int(cid[1:]) + 50),
                "sender_name": sender if cid != "N06" else None,
                "receiver_name": MERCHANT_RECEIVER,
                "claimed_offset_min": -10,
                "raw_timestamp_text": "20 Aug 2026" if cid != "N05" else None,
            },
            "ledger": [
                {
                    "rail": "jazzcash",
                    "amount_paisa": amt,
                    "external_transaction_id": demo_txn_ref("jazzcash", int(cid[1:]) + 50),
                    "sender_name": sender,
                    "receiver_name": MERCHANT_RECEIVER,
                    "ledger_offset_min": -11,
                    "status": "POSTED",
                    "trust_level": "SIMULATOR",
                },
            ],
            "allocations": [],
            "order": {
                "external_order_ref": f"ORD-{cid}",
                "expected_amount_paisa": amt,
            },
            "expected": {
                "outcome": "NEEDS_REVIEW",
                "reason_code": "LOW_EXTRACTION_CONFIDENCE",
                },
        })

    # Attach the receipt hashes last, so `images` stays the final key of every
    # case exactly where hash_images.py used to append it. A None back from
    # `_image_meta` means "no image on disk and the caller said that is fine";
    # the key is then left off entirely rather than set to null, because every
    # reader in the repo guards with `case.get("images", {})` and a null value
    # defeats that guard while an absent key does not.
    for case in cases:
        meta = _image_meta(case["id"], allow_missing=allow_missing_images)
        if meta is not None:
            case["images"] = meta

    # Master manifest structure
    manifest_data = {
        "version": "1.0.0",
        "description": "ProofPay 30-case demo fixture manifest (single source of truth)",
        "total_cases": len(cases),
        "category_counts": {
            "VERIFIED": sum(1 for c in cases if c["category"] == "VERIFIED"),
            "UNMATCHED": sum(1 for c in cases if c["category"] == "UNMATCHED"),
            "SUSPICIOUS": sum(1 for c in cases if c["category"] == "SUSPICIOUS"),
            "DUPLICATE": sum(1 for c in cases if c["category"] == "DUPLICATE"),
            "NEEDS_REVIEW": sum(1 for c in cases if c["category"] == "NEEDS_REVIEW"),
        },
        "cases": cases,
    }

    return manifest_data


def main():
    """Generate manifest and write to fixtures/demo/manifest.json."""
    parser = argparse.ArgumentParser(
        description="Generate fixtures/demo/manifest.json from this script's case data."
    )
    parser.add_argument(
        "--allow-missing-images",
        action="store_true",
        help=(
            "Emit a case with no `images` block instead of aborting when its receipt "
            "JPEG does not exist yet. Bootstrap only: render_receipts.py reads the "
            "manifest, so a brand-new case needs one pass with this flag before its "
            "image can be rendered. Rebuild without the flag before committing."
        ),
    )
    args = parser.parse_args()

    manifest = generate_manifest(allow_missing_images=args.allow_missing_images)

    out_dir = REPO_ROOT / "fixtures" / "demo"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "manifest.json"

    # newline="\n" prevents a whole-file line-ending rewrite on Windows
    # checkouts: without it Python translates all 1,100+ newlines to CRLF, and
    # .gitattributes hides that in the diff while every sha256-of-the-manifest
    # check sees a completely different file.
    with open(out_file, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    # Plain ASCII, not a "✓": Python encodes stdout with the console codepage,
    # which is cp1252 on a default Windows shell, and a UnicodeEncodeError here
    # would exit 1 AFTER the manifest was written — a generator that reports
    # failure on success is exactly how someone ends up hand-editing the JSON.
    print(f"OK  Manifest successfully written to: {out_file}")
    print(f"  Total cases: {manifest['total_cases']}")
    for cat, count in manifest['category_counts'].items():
        print(f"    - {cat}: {count}")


if __name__ == "__main__":
    main()
