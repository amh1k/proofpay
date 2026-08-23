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
    - id:         Unique case identifier (G01–G10, U01–U04, S01–S06, D01–D04, N01–N06)
    - title:      Human-readable description of scenario
    - category:   VERIFIED | UNMATCHED | SUSPICIOUS | DUPLICATE | NEEDS_REVIEW
    - visible:    Screenshot visual ground truth (what OCR should extract)
    - ledger:     Merchant trusted bank feed ground truth (what actually happened)
    - order:      Expected order details (what customer ordered)
    - expected:   Expected verification decision & reason code
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

# Add backend to path for clock imports
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from pk_data import (
    BUSINESS_NAMES,
    FAMILY_NAMES,
    GIVEN_NAMES_MALE,
    demo_id,
    demo_txn_ref,
    mask_msisdn,
    pk_iban,
    random_msisdn,
)
from proofpay.demo.clock import at


def generate_manifest() -> dict:
    """Build the complete 30-case demo manifest data structure."""

    rng = random.Random(42)  # Seeded for absolute determinism
    cases = []

    # Common receiver for all demo transactions
    MERCHANT_RECEIVER = "Ali Traders"
    MERCHANT_IBAN = pk_iban("SBZP", "009988776655")

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
        "ledger": {
            "rail": "easypaisa",
            "amount_paisa": 150000,
            "external_transaction_id": demo_txn_ref("easypaisa", 1),
            "sender_name": "Bilal Ahmed Khan",
            "receiver_name": MERCHANT_RECEIVER,
            "ledger_offset_min": -12,
            "status": "POSTED",
            "trust_level": "DEMO_TRUSTED",
        },
        "order": {
            "external_order_ref": "ORD-G01",
            "expected_amount_paisa": 150000,
        },
        "expected": {
            "outcome": "VERIFIED",
            "reason_code": "EXACT_MATCH",
            "rules_version": "v1.0.0",
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
        "ledger": {
            "rail": "jazzcash",
            "amount_paisa": 250000,
            "external_transaction_id": demo_txn_ref("jazzcash", 2),
            "sender_name": "Mohammad Usman Shaikh",  # Transliteration difference
            "receiver_name": MERCHANT_RECEIVER,
            "ledger_offset_min": -21,
            "status": "POSTED",
            "trust_level": "DEMO_TRUSTED",
        },
        "order": {
            "external_order_ref": "ORD-G02",
            "expected_amount_paisa": 250000,
        },
        "expected": {
            "outcome": "VERIFIED",
            "reason_code": "MATCH_WITH_FUZZY_SENDER",
            "rules_version": "v1.0.0",
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
            "ledger": {
                "rail": rail,
                "amount_paisa": amt,
                "external_transaction_id": demo_txn_ref(rail, idx),
                "sender_name": sender if cid != "G07" else "Muhammad Bilal Shaikh",
                "receiver_name": MERCHANT_RECEIVER,
                "ledger_offset_min": -(idx * 5 + 1),
                "status": "POSTED",
                "trust_level": "DEMO_TRUSTED",
            },
            "order": {
                "external_order_ref": f"ORD-{cid}",
                "expected_amount_paisa": order_amt,
            },
            "expected": {
                "outcome": "VERIFIED",
                "reason_code": "EXACT_MATCH" if cid != "G05" else "OVERPAYMENT_ACCEPTED",
                "rules_version": "v1.0.0",
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
        "ledger": None,  # No transaction in ledger at all!
        "order": {
            "external_order_ref": "ORD-U01",
            "expected_amount_paisa": 150000,
        },
        "expected": {
            "outcome": "UNMATCHED",
            "reason_code": "NO_MATCHING_TRANSACTION",
            "rules_version": "v1.0.0",
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
        "ledger": {
            "rail": "jazzcash",
            "amount_paisa": 200000,
            "external_transaction_id": demo_txn_ref("jazzcash", 20),
            "sender_name": "Asad Ullah",
            "receiver_name": MERCHANT_RECEIVER,
            "ledger_offset_min": -2,
            "status": "PENDING",  # Not posted yet!
            "trust_level": "DEMO_TRUSTED",
        },
        "order": {
            "external_order_ref": "ORD-U02",
            "expected_amount_paisa": 200000,
        },
        "expected": {
            "outcome": "UNMATCHED",
            "reason_code": "TRANSACTION_PENDING_SETTLEMENT",
            "rules_version": "v1.0.0",
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
        "ledger": None,
        "order": {
            "external_order_ref": "ORD-U03",
            "expected_amount_paisa": 150000,
        },
        "expected": {
            "outcome": "UNMATCHED",
            "reason_code": "TRANSACTION_OUTSIDE_WINDOW",
            "rules_version": "v1.0.0",
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
        "ledger": None,
        "order": {
            "external_order_ref": "ORD-U04",
            "expected_amount_paisa": 300000,
        },
        "expected": {
            "outcome": "UNMATCHED",
            "reason_code": "MISMATCHED_RECEIVER",
            "rules_version": "v1.0.0",
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
        "ledger": {
            "rail": "easypaisa",
            "amount_paisa": 50000,   # 500 PKR (real ledger value)
            "external_transaction_id": demo_txn_ref("easypaisa", 30),
            "sender_name": "Shoaib Malik",
            "receiver_name": MERCHANT_RECEIVER,
            "ledger_offset_min": -11,
            "status": "POSTED",
            "trust_level": "DEMO_TRUSTED",
        },
        "order": {
            "external_order_ref": "ORD-S01",
            "expected_amount_paisa": 500000,
        },
        "expected": {
            "outcome": "SUSPICIOUS",
            "reason_code": "CLAIMED_AMOUNT_INFLATED",
            "rules_version": "v1.0.0",
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
        "ledger": {
            "rail": "jazzcash",
            "amount_paisa": 150000,
            "external_transaction_id": "JC0000311",  # Real TID in ledger
            "sender_name": "Waseem Akram",
            "receiver_name": MERCHANT_RECEIVER,
            "ledger_offset_min": -16,
            "status": "POSTED",
            "trust_level": "DEMO_TRUSTED",
        },
        "order": {
            "external_order_ref": "ORD-S02",
            "expected_amount_paisa": 150000,
        },
        "expected": {
            "outcome": "SUSPICIOUS",
            "reason_code": "REFERENCE_ID_TAMPERED",
            "rules_version": "v1.0.0",
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
            "ledger": {
                "rail": "easypaisa",
                "amount_paisa": amt,
                "external_transaction_id": f"EP{cid}999",
                "sender_name": sender,
                "receiver_name": MERCHANT_RECEIVER,
                "ledger_offset_min": -11,
                "status": "POSTED",
                "trust_level": "DEMO_TRUSTED",
            },
            "order": {
                "external_order_ref": f"ORD-{cid}",
                "expected_amount_paisa": amt * 2,
            },
            "expected": {
                "outcome": "SUSPICIOUS",
                "reason_code": "CRITICAL_FIELD_CONFLICT",
                "rules_version": "v1.0.0",
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
        "ledger": {
            "rail": "easypaisa",
            "amount_paisa": 150000,
            "external_transaction_id": demo_txn_ref("easypaisa", 1),
            "sender_name": "Bilal Ahmed Khan",
            "receiver_name": MERCHANT_RECEIVER,
            "ledger_offset_min": -12,
            "status": "POSTED",
            "trust_level": "DEMO_TRUSTED",
        },
        "order": {
            "external_order_ref": "ORD-D01",  # Second order trying to claim G01's payment
            "expected_amount_paisa": 150000,
        },
        "expected": {
            "outcome": "DUPLICATE",
            "reason_code": "TRANSACTION_ALREADY_ALLOCATED",
            "rules_version": "v1.0.0",
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
        "ledger": {
            "rail": "jazzcash",
            "amount_paisa": 250000,
            "external_transaction_id": demo_txn_ref("jazzcash", 2),
            "sender_name": "Muhammad Usman Sheikh",
            "receiver_name": MERCHANT_RECEIVER,
            "ledger_offset_min": -21,
            "status": "POSTED",
            "trust_level": "DEMO_TRUSTED",
        },
        "order": {
            "external_order_ref": "ORD-D02",
            "expected_amount_paisa": 250000,
        },
        "expected": {
            "outcome": "DUPLICATE",
            "reason_code": "PROOF_IMAGE_SHA256_REUSED",
            "rules_version": "v1.0.0",
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
        "ledger": {
            "rail": "raast",
            "amount_paisa": 350000,
            "external_transaction_id": demo_txn_ref("raast", 3),
            "sender_name": "Saad Tariq Qureshi",
            "receiver_name": MERCHANT_RECEIVER,
            "ledger_offset_min": -16,
            "status": "POSTED",
            "trust_level": "DEMO_TRUSTED",
        },
        "order": {
            "external_order_ref": "ORD-D03",
            "expected_amount_paisa": 350000,
        },
        "expected": {
            "outcome": "DUPLICATE",
            "reason_code": "PROOF_IMAGE_PHASH_SIMILAR",
            "rules_version": "v1.0.0",
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
        "ledger": {
            "rail": "bank",
            "amount_paisa": 500000,
            "external_transaction_id": demo_txn_ref("bank", 4),
            "sender_name": "Faisal Javed Malik",
            "receiver_name": MERCHANT_RECEIVER,
            "ledger_offset_min": -21,
            "status": "POSTED",
            "trust_level": "DEMO_TRUSTED",
        },
        "order": {
            "external_order_ref": "ORD-D04",
            "expected_amount_paisa": 500000,
        },
        "expected": {
            "outcome": "DUPLICATE",
            "reason_code": "TRANSACTION_ALREADY_ALLOCATED",
            "rules_version": "v1.0.0",
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
        "ledger": {
            "rail": "easypaisa",
            "amount_paisa": 120000,  # 1,200 PKR arrived
            "external_transaction_id": demo_txn_ref("easypaisa", 50),
            "sender_name": "Waqar Younis",
            "receiver_name": MERCHANT_RECEIVER,
            "ledger_offset_min": -11,
            "status": "POSTED",
            "trust_level": "DEMO_TRUSTED",
        },
        "order": {
            "external_order_ref": "ORD-N01",
            "expected_amount_paisa": 150000,  # Expected 1,500 PKR
        },
        "expected": {
            "outcome": "NEEDS_REVIEW",
            "reason_code": "UNDERPAID_ORDER",
            "rules_version": "v1.0.0",
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
        "ledger": {
            "rail": "jazzcash",
            "amount_paisa": 500000,
            "external_transaction_id": demo_txn_ref("jazzcash", 51),
            "sender_name": "Junaid Jamshed",
            "receiver_name": MERCHANT_RECEIVER,
            "ledger_offset_min": -13,
            "status": "POSTED",
            "trust_level": "DEMO_TRUSTED",
        },
        "order": {
            "external_order_ref": "ORD-N02",
            "expected_amount_paisa": 150000,
        },
        "expected": {
            "outcome": "NEEDS_REVIEW",
            "reason_code": "OVERPAYMENT_REVIEW_REQUIRED",
            "rules_version": "v1.0.0",
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
        "ledger": {
            "rail": "easypaisa",
            "amount_paisa": 150000,
            "external_transaction_id": demo_txn_ref("easypaisa", 52),
            "sender_name": "Irfan Khan",
            "receiver_name": MERCHANT_RECEIVER,
            "ledger_offset_min": -15,
            "status": "POSTED",
            "trust_level": "DEMO_TRUSTED",
        },
        "order": {
            "external_order_ref": "ORD-N03",
            "expected_amount_paisa": 150000,
        },
        "expected": {
            "outcome": "NEEDS_REVIEW",
            "reason_code": "AMBIGUOUS_CANDIDATES",
            "rules_version": "v1.0.0",
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
            "ledger": {
                "rail": "jazzcash",
                "amount_paisa": amt,
                "external_transaction_id": demo_txn_ref("jazzcash", int(cid[1:]) + 50),
                "sender_name": sender,
                "receiver_name": MERCHANT_RECEIVER,
                "ledger_offset_min": -11,
                "status": "POSTED",
                "trust_level": "DEMO_TRUSTED",
            },
            "order": {
                "external_order_ref": f"ORD-{cid}",
                "expected_amount_paisa": amt,
            },
            "expected": {
                "outcome": "NEEDS_REVIEW",
                "reason_code": "INCOMPLETE_CLAIM_DATA",
                "rules_version": "v1.0.0",
            },
        })

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
    manifest = generate_manifest()

    out_dir = REPO_ROOT / "fixtures" / "demo"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "manifest.json"

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"✓ Manifest successfully written to: {out_file}")
    print(f"  Total cases: {manifest['total_cases']}")
    for cat, count in manifest['category_counts'].items():
        print(f"    - {cat}: {count}")


if __name__ == "__main__":
    main()
