"""Tests for tools/pk_data.py — Pakistani data generators and deterministic IDs.

These tests verify that:
  - UUID5 IDs are deterministic (same input → same output, always)
  - Phone numbers use real PTA prefixes and are reproducible with a seed
  - Phone masking matches real Pakistani app behaviour
  - IBANs are 24 chars with valid mod-97 check digits
  - Transaction references have correct rail-specific prefixes
  - All name/data lists are populated at expected sizes
"""

import random
import sys
from pathlib import Path

import pytest

# tools/ is at the repo root, not inside backend/, so we add it to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from pk_data import (
    BUSINESS_NAMES,
    FAMILY_NAMES,
    FICTIONAL_BANK_CODES,
    GIVEN_NAMES_FEMALE,
    GIVEN_NAMES_MALE,
    OPERATOR_PREFIXES,
    TRANSLIT_VARIANTS,
    demo_id,
    demo_txn_ref,
    mask_msisdn,
    pk_iban,
    random_msisdn,
)

# ── Deterministic ID generation ──────────────────────────────────


class TestDemoId:
    """demo_id() must produce stable, collision-free UUID5 values."""

    def test_same_inputs_give_same_uuid(self):
        """Calling demo_id with identical args must return the same UUID."""
        assert demo_id("order", "G01") == demo_id("order", "G01")

    def test_different_keys_give_different_uuids(self):
        """Different case keys must produce different UUIDs."""
        assert demo_id("order", "G01") != demo_id("order", "G02")

    def test_different_kinds_give_different_uuids(self):
        """Same key but different entity kind must produce different UUIDs."""
        assert demo_id("order", "G01") != demo_id("txn", "G01")

    def test_result_is_uuid(self):
        """Return value must be a proper uuid.UUID instance."""
        import uuid
        result = demo_id("merchant", "demo")
        assert isinstance(result, uuid.UUID)


# ── Phone number generation ──────────────────────────────────────


class TestRandomMsisdn:
    """random_msisdn() must produce valid Pakistani mobile numbers."""

    def test_length_is_11_digits(self):
        """Pakistani mobile numbers are exactly 11 digits."""
        rng = random.Random(42)
        phone = random_msisdn(rng)
        assert len(phone) == 11
        assert phone.isdigit()

    def test_prefix_is_valid_pta(self):
        """The first 4 digits must be a real PTA operator prefix."""
        all_prefixes = [p for group in OPERATOR_PREFIXES.values() for p in group]
        rng = random.Random(42)
        for _ in range(20):  # Generate 20 numbers, all should have valid prefixes
            phone = random_msisdn(rng)
            assert phone[:4] in all_prefixes, f"Invalid prefix: {phone[:4]}"

    def test_same_seed_gives_same_number(self):
        """Seeded RNG must produce reproducible results across runs."""
        phone1 = random_msisdn(random.Random(42))
        phone2 = random_msisdn(random.Random(42))
        assert phone1 == phone2

    def test_specific_operator(self):
        """Requesting a specific operator should use only that operator's prefixes."""
        rng = random.Random(99)
        phone = random_msisdn(rng, operator="telenor")
        assert phone[:4] in OPERATOR_PREFIXES["telenor"]


# ── Phone masking ─────────────────────────────────────────────────


class TestMaskMsisdn:
    """mask_msisdn() must match real Pakistani app masking format."""

    def test_standard_masking(self):
        """'03014567890' should become '0301-****890'."""
        assert mask_msisdn("03014567890") == "0301-****890"

    def test_preserves_prefix_and_suffix(self):
        """First 4 and last 3 digits must be visible."""
        masked = mask_msisdn("03401234567")
        assert masked.startswith("0340")
        assert masked.endswith("567")
        assert "****" in masked


# ── IBAN generation ───────────────────────────────────────────────


class TestPkIban:
    """pk_iban() must generate structurally valid Pakistani IBANs."""

    def test_length_is_24(self):
        """Pakistani IBANs are exactly 24 characters."""
        iban = pk_iban("SBZP", "12345678")
        assert len(iban) == 24

    def test_starts_with_pk(self):
        """Must start with country code 'PK'."""
        iban = pk_iban("INDU", "99887766")
        assert iban[:2] == "PK"

    def test_bank_code_at_position_4(self):
        """Bank code occupies positions 4–7."""
        iban = pk_iban("NRPY", "11111111")
        assert iban[4:8] == "NRPY"

    def test_check_digits_are_valid_mod97(self):
        """The IBAN must pass ISO 7064 mod-97 validation.

        Algorithm: move first 4 chars to end, convert letters to numbers,
        the resulting number mod 97 must equal 1.
        """
        iban = pk_iban("SBZP", "12345678")
        # Rearrange: bank+account+country+check → all to numbers
        rearranged = iban[4:] + iban[:4]
        num_str = "".join(str(int(c, 36)) for c in rearranged)
        assert int(num_str) % 97 == 1

    @pytest.mark.parametrize("bank_code", FICTIONAL_BANK_CODES.keys())
    def test_all_fictional_banks_produce_valid_ibans(self, bank_code):
        """Every fictional bank code must produce a valid IBAN."""
        iban = pk_iban(bank_code, "55555555")
        assert len(iban) == 24
        rearranged = iban[4:] + iban[:4]
        num_str = "".join(str(int(c, 36)) for c in rearranged)
        assert int(num_str) % 97 == 1


# ── Transaction references ───────────────────────────────────────


class TestDemoTxnRef:
    """demo_txn_ref() must produce rail-prefixed, deterministic references."""

    @pytest.mark.parametrize("rail,prefix", [
        ("easypaisa", "EP"),
        ("jazzcash", "JC"),
        ("raast", "RA"),
        ("bank", "BK"),
    ])
    def test_rail_prefix(self, rail, prefix):
        """Each rail must get its correct 2-letter prefix."""
        ref = demo_txn_ref(rail, 1)
        assert ref.startswith(prefix), f"Expected {prefix}..., got {ref}"

    def test_unknown_rail_uses_tx_prefix(self):
        """Unknown rails should fall back to 'TX' prefix."""
        ref = demo_txn_ref("unknown_provider", 1)
        assert ref.startswith("TX")

    def test_deterministic(self):
        """Same inputs must always produce the same reference."""
        assert demo_txn_ref("easypaisa", 5) == demo_txn_ref("easypaisa", 5)

    def test_different_indices_differ(self):
        """Different case indices must produce different references."""
        assert demo_txn_ref("easypaisa", 1) != demo_txn_ref("easypaisa", 2)


# ── Data list integrity ──────────────────────────────────────────


class TestDataLists:
    """Verify all curated data lists have the expected content."""

    def test_male_names_count(self):
        assert len(GIVEN_NAMES_MALE) == 30

    def test_female_names_count(self):
        assert len(GIVEN_NAMES_FEMALE) == 20

    def test_family_names_count(self):
        assert len(FAMILY_NAMES) == 40

    def test_business_names_populated(self):
        assert len(BUSINESS_NAMES) >= 10

    def test_transliteration_groups(self):
        assert len(TRANSLIT_VARIANTS) >= 8

    def test_fictional_bank_codes(self):
        assert len(FICTIONAL_BANK_CODES) == 4

    def test_no_duplicate_male_names(self):
        assert len(GIVEN_NAMES_MALE) == len(set(GIVEN_NAMES_MALE))

    def test_no_duplicate_family_names(self):
        assert len(FAMILY_NAMES) == len(set(FAMILY_NAMES))
