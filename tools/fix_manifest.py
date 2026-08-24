
path = 'C:/fastapi/proofpay/tools/build_manifest.py'
content = open(path, encoding='utf-8').read()

replacements = {
    '"EXACT_MATCH"': '"STRONG_FIELD_AGREEMENT"',
    '"CRITICAL_FIELD_CONFLICT"': '"FIELD_CONTRADICTS_MATCH"',
    '"INCOMPLETE_CLAIM_DATA"': '"LOW_EXTRACTION_CONFIDENCE"',
    '"TRANSACTION_ALREADY_ALLOCATED"': '"TXN_ALREADY_ALLOCATED"',
    '"CLAIMED_AMOUNT_INFLATED"': '"CLAIM_INFLATED"',
    '"MATCH_WITH_FUZZY_SENDER"': '"STRONG_FIELD_AGREEMENT"',
    '"MISMATCHED_RECEIVER"': '"NAME_MISMATCH"',
    '"NO_MATCHING_TRANSACTION"': '"NO_CANDIDATES"',
    '"TRANSACTION_PENDING_SETTLEMENT"': '"NO_CANDIDATES"',
    '"OVERPAYMENT_ACCEPTED"': '"AMOUNT_OVERPAID"',
    '"OVERPAYMENT_REVIEW_REQUIRED"': '"AMOUNT_OVERPAID"',
    '"UNDERPAID_ORDER"': '"AMOUNT_UNDERPAID"',
    '"REFERENCE_ID_TAMPERED"': '"REFERENCE_MISMATCH"',
    '"TRANSACTION_OUTSIDE_WINDOW"': '"TIMESTAMP_MISMATCH"',
    '"PROOF_IMAGE_SHA256_REUSED"': '"PROOF_REUSED"',
    '"PROOF_IMAGE_PHASH_SIMILAR"': '"PROOF_REUSED"',
    '"trust_level": "DEMO_TRUSTED"': '"trust_level": "SIMULATOR"',
    '            "rules_version": "v1.0.0",\n': '',
    '            "rules_version": "v1.0.0"\n': '',
    '    rng = random.Random(42)  # Seeded for absolute determinism\n': ''
}

for old, new in replacements.items():
    content = content.replace(old, new)

open(path, 'w', encoding='utf-8').write(content)
