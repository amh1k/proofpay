"""Curated Pakistani names, phone prefixes, and identifier generators.

WHY THIS FILE EXISTS:
    The Faker library's en_PK locale only has a basic person provider, and its
    names skew Arabic-classical (e.g. "Najam Ghazzal") rather than everyday
    Pakistani-urban (e.g. "Bilal Ahmed Khan"). For a hackathon demo judged
    in Pakistan, the names need to look right at a glance.

    This module provides:
      - Common Pakistani male/female given names and family names
      - Transliteration variants (the core challenge for fuzzy matching)
      - Real PTA mobile prefixes with fictional subscriber digits
      - IBAN generation with fictional bank codes (no real bank references)
      - Deterministic UUID5 IDs so every entity has a stable, reproducible key

HOW IT'S USED:
    Run ONCE at authoring time to populate manifest.json.
    NEVER called at seed time or test time — all generated data is frozen
    into the manifest so it can't drift across machines or library versions.
"""

from __future__ import annotations

import random
import uuid


# ═══════════════════════════════════════════════════════════════════
# DETERMINISTIC ID GENERATION
# ═══════════════════════════════════════════════════════════════════
# We derive every entity's primary key from a UUID5 namespace + a
# human-readable case key (like "G01" or "S03"). This means:
#   - IDs are the same on every machine, every run (no randomness)
#   - No auto-increment dependency on DB insertion order
#   - No DB round-trip needed to know an entity's ID ahead of time
#   - Two people seeding independently get identical UUIDs
# ═══════════════════════════════════════════════════════════════════

NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://proofpay.demo/v1")


def demo_id(kind: str, key: str) -> uuid.UUID:
    """Generate a stable UUID5 for a demo entity.

    Args:
        kind: Entity type, e.g. "merchant", "order", "txn"
        key:  Case identifier, e.g. "G01", "S03:0" (for indexed sub-entities)

    Returns:
        A UUID that is always the same for the same (kind, key) pair.

    Example:
        demo_id("order", "G01")  → always UUID('a1b2c3d4-...')
        demo_id("txn", "G01:0") → always UUID('e5f6a7b8-...')
    """
    return uuid.uuid5(NS, f"proofpay:demo:{kind}:{key}")


# ═══════════════════════════════════════════════════════════════════
# CURATED PAKISTANI NAMES
# ═══════════════════════════════════════════════════════════════════
# These are common names you'd see in Karachi, Lahore, Islamabad —
# not the classical Arabic names that Faker's en_PK generates.
# 30 male + 20 female given names × 40 family names = 2,000 combos.
# We only need ~30 for fixtures, so this is more than enough.
# ═══════════════════════════════════════════════════════════════════

GIVEN_NAMES_MALE = [
    "Muhammad", "Ali", "Ahmed", "Bilal", "Usman", "Hassan", "Hamza",
    "Fahad", "Omar", "Saad", "Imran", "Kamran", "Kashif", "Faisal",
    "Asad", "Tariq", "Salman", "Zubair", "Shoaib", "Waseem",
    "Rizwan", "Adeel", "Naveed", "Waqar", "Junaid", "Irfan",
    "Arslan", "Danish", "Shahid", "Nadeem",
]

GIVEN_NAMES_FEMALE = [
    "Ayesha", "Fatima", "Sana", "Hira", "Mahnoor", "Rabia",
    "Zainab", "Amna", "Nadia", "Saima", "Bushra", "Asma",
    "Kiran", "Mehreen", "Sobia", "Uzma", "Noor", "Iqra",
    "Samina", "Farah",
]

FAMILY_NAMES = [
    "Khan", "Ahmed", "Ali", "Sheikh", "Malik", "Hussain",
    "Siddiqui", "Qureshi", "Butt", "Iqbal", "Rehman", "Shah",
    "Raza", "Javed", "Aslam", "Mirza", "Chaudhry", "Nawaz",
    "Farooq", "Abbasi", "Baig", "Hashmi", "Zaidi", "Bhatti",
    "Akhtar", "Anwar", "Gill", "Mughal", "Paracha", "Durrani",
    "Ghani", "Shaikh", "Naqvi", "Haider", "Memon", "Baloch",
    "Arif", "Saeed", "Yousuf", "Rashid",
]

# Business names for merchant/receiver fields on receipts.
BUSINESS_NAMES = [
    "Ali Traders", "Karachi Electronics", "Lahore Garments",
    "City Mobile Shop", "Al-Noor General Store", "Pak Courier Express",
    "Bismillah Cloth House", "Madina Cash & Carry", "Star Auto Parts",
    "Ghani Brothers", "Hassan Medical Store", "Islamabad Books",
]


# ═══════════════════════════════════════════════════════════════════
# TRANSLITERATION VARIANTS
# ═══════════════════════════════════════════════════════════════════
# Urdu → Latin has no single correct spelling. The SAME person's name
# appears differently on their Easypaisa account vs their bank record:
#   - "Muhammad" on the screenshot, "Mohammad" in the ledger
#   - "Shaikh" on one side, "Sheikh" on the other
#
# This is the CORE CHALLENGE for the fuzzy name matcher (Track A).
# Each fixture case deliberately tests one variation axis so that
# when a test fails, the failure names the exact linguistic phenomenon
# it broke on (e.g. "consonant_cluster") rather than just a score.
# ═══════════════════════════════════════════════════════════════════

TRANSLIT_VARIANTS: dict[str, list[str]] = {
    "muhammad":  ["mohammad", "mohammed", "mohd", "md"],
    "sheikh":    ["shaikh", "shaykh"],
    "rehman":    ["rahman", "rehmaan"],
    "siddiqui":  ["siddiqi", "sadiqui"],
    "qureshi":   ["qureishi", "quraishi"],
    "ahmed":     ["ahmad"],
    "hussain":   ["husain", "hossain"],
    "ali":       ["aly"],
}


# ═══════════════════════════════════════════════════════════════════
# PHONE NUMBER GENERATION
# ═══════════════════════════════════════════════════════════════════
# We use REAL PTA (Pakistan Telecom Authority) operator prefixes so
# numbers look authentic to a Pakistani judge. The subscriber digits
# (last 7) are random/fictional — no real person's number is used.
#
# Format on receipts: "03014567890"
# Masked like real apps: "0301-****890" (middle 4 digits hidden)
# ═══════════════════════════════════════════════════════════════════

OPERATOR_PREFIXES: dict[str, list[str]] = {
    "jazz":    [  # Jazz (including former Warid) — largest operator
        "0300", "0301", "0302", "0303", "0304", "0305",
        "0306", "0307", "0308", "0309", "0320", "0321",
        "0322", "0323", "0324", "0325", "0326", "0327",
        "0328", "0329",
    ],
    "zong":    [  # Zong (China Mobile subsidiary)
        "0310", "0311", "0312", "0313", "0314", "0315",
        "0316", "0317", "0318", "0319", "0370",
    ],
    "ufone":   [  # Ufone (PTCL subsidiary)
        "0330", "0331", "0332", "0333", "0334", "0335",
        "0336", "0337", "0338",
    ],
    "telenor": [  # Telenor Pakistan
        "0340", "0341", "0342", "0343", "0344", "0345",
        "0346", "0347", "0348", "0349",
    ],
}


def random_msisdn(rng: random.Random, operator: str | None = None) -> str:
    """Generate a plausible Pakistani mobile number.

    Args:
        rng:      A seeded Random instance for reproducibility.
        operator: Optional operator name ('jazz', 'zong', etc.).
                  If None, picks from all operators.

    Returns:
        An 11-digit string like '03014567890'.

    Why seeded Random instead of random.choice():
        We want the SAME numbers every time this script runs with the
        same seed, so the manifest doesn't change between runs.
    """
    if operator:
        prefixes = OPERATOR_PREFIXES[operator]
    else:
        # Flatten all prefixes from all operators into one list
        prefixes = [p for group in OPERATOR_PREFIXES.values() for p in group]
    prefix = rng.choice(prefixes)
    # Generate 7 random subscriber digits
    subscriber = "".join(str(rng.randint(0, 9)) for _ in range(7))
    return f"{prefix}{subscriber}"


def mask_msisdn(msisdn: str) -> str:
    """Mask a phone number the way real Pakistani payment apps do.

    '03014567890' → '0301-****890'

    Real apps (Easypaisa, JazzCash) mask the middle digits for privacy.
    We reproduce this because the masked form is what appears on
    screenshots, and the fuzzy matcher must handle it.
    """
    return f"{msisdn[:4]}-****{msisdn[-3:]}"


# ═══════════════════════════════════════════════════════════════════
# PAKISTANI IBAN GENERATION
# ═══════════════════════════════════════════════════════════════════
# Pakistani IBAN structure: PK + 2 check digits + 4 bank code + 16 account
# Total: 24 characters.
#
# We use FICTIONAL bank codes (SBZP, NRPY, INDU, PKDM) so no real
# bank's code appears in our fixtures. The check digits are computed
# correctly using the mod-97 algorithm (ISO 7064), so the IBANs pass
# basic validation — important because a template regex might validate
# the format and reject obviously fake ones.
# ═══════════════════════════════════════════════════════════════════

FICTIONAL_BANK_CODES: dict[str, str] = {
    "SBZP": "SabzPay",           # Our fictional Easypaisa equivalent
    "NRPY": "NoorPay",           # Our fictional JazzCash equivalent
    "INDU": "Indus Bank",        # Our fictional bank
    "PKDM": "Pakistan Demo Bank",
}


def pk_iban(bank_code: str, account: str) -> str:
    """Generate a valid Pakistani IBAN with correct mod-97 check digits.

    Args:
        bank_code: 4-letter bank code (use fictional ones from FICTIONAL_BANK_CODES)
        account:   Account number (will be zero-padded to 16 digits)

    Returns:
        24-character IBAN like 'PK36SBZP0000000012345678'

    Algorithm (ISO 7064 / mod-97):
        1. Form the string: bank_code + padded_account + "PK00"
        2. Convert each letter to its numeric value (A=10, B=11, ..., Z=35)
        3. Compute: check = 98 - (numeric_string mod 97)
        4. Result: "PK" + check_digits + bank_code + padded_account
    """
    # Zero-pad the account number to exactly 16 digits
    padded = f"{account:0>16}"

    # Build the string for mod-97: bank + account + country("PK") + placeholder("00")
    body = f"{bank_code}{padded}PK00"

    # Convert each character to its base-36 numeric value
    # Letters: A=10, B=11, ..., Z=35.  Digits: 0=0, ..., 9=9.
    num_str = "".join(str(int(c, 36)) for c in body)

    # ISO 7064 mod-97 check
    check = 98 - (int(num_str) % 97)

    return f"PK{check:02d}{bank_code}{padded}"


# ═══════════════════════════════════════════════════════════════════
# TRANSACTION REFERENCE GENERATORS
# ═══════════════════════════════════════════════════════════════════
# Each payment provider has its own reference format. We create
# deterministic, human-readable refs with a rail-specific prefix
# and a simple check digit for a touch of realism.
#
# These refs appear both on the receipt screenshot (extracted by OCR)
# and in the merchant's ledger (the source of truth), so the matcher
# can compare them.
# ═══════════════════════════════════════════════════════════════════

def demo_txn_ref(rail: str, case_index: int) -> str:
    """Generate a deterministic transaction reference for a demo case.

    Args:
        rail:       Payment rail ('easypaisa', 'jazzcash', 'raast', 'bank')
        case_index: Numeric index for this case (used in the reference)

    Returns:
        A reference like 'EP0000010' (Easypaisa, case 1, check digit 0)

    The check digit is a simple mod-7 sum of the digits — enough to
    make OCR grammar tests meaningful without implementing Luhn.
    """
    # Map each rail to a 2-letter prefix that looks like the real thing
    prefixes = {
        "easypaisa": "EP",   # Easypaisa-style TID
        "jazzcash":  "JC",   # JazzCash-style TID
        "raast":     "RA",   # Raast RRN
        "bank":      "BK",   # Bank IBFT reference
    }
    prefix = prefixes.get(rail, "TX")

    # Zero-pad to 6 digits for consistent length
    base = f"{case_index:06d}"

    # Simple check digit: sum of all digits mod 7
    check = sum(int(d) for d in base) % 7

    return f"{prefix}{base}{check}"
