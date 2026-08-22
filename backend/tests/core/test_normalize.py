"""Normalisation is the highest-leverage code in the phase, so it gets a table.

Every amount string here came off a real Pakistani wallet receipt or is a
documented OCR failure mode.
"""

from decimal import Decimal

import pytest

from proofpay.core.money import Money
from proofpay.core.normalize import (
    HONORIFICS,
    fold_digits,
    fold_token,
    nfkc,
    normalize_name,
    normalize_reference,
    parse_amount_money,
    parse_amount_text,
    reference_confusable_key,
)
from proofpay.core.reasons import ObservationCode

GLYPH = ObservationCode.AMOUNT_OCR_GLYPH_FIXUP
AMBIG = ObservationCode.AMOUNT_SEPARATOR_AMBIGUOUS
NON_ASCII = ObservationCode.AMOUNT_NON_ASCII_DIGITS

# Arabic-Indic digits and separators, as they arrive off an Urdu-locale device.
ARABIC_1500 = "١٥٠٠"
ARABIC_THOUSANDS_SEP = "٬"   # U+066C thousands
ARABIC_DECIMAL_SEP = "٫"     # U+066B decimal


class TestParseAmountText:
    @pytest.mark.parametrize(
        "raw,value,notes",
        [
            # --- the everyday cases -------------------------------------
            ("Rs. 1,500", Decimal("1500"), []),
            ("PKR 1,500.00", Decimal("1500.00"), []),
            ("Rs 1500/-", Decimal("1500"), []),
            ("PKR 250", Decimal("250"), []),
            ("1,500,000", Decimal("1500000"), []),
            ("Rs 1,234.56", Decimal("1234.56"), []),
            ("Total: Rs. 12,345/-", Decimal("12345"), []),
            ("Bill Rs 2,000 only", Decimal("2000"), []),
            ("Rs. 0", Decimal("0"), []),
            ("1 500", Decimal("1500"), []),                       # space-grouped
            ("Rs. 1,500", Decimal("1500"), []),              # non-breaking space
            # --- non-ASCII digits and separators ------------------------
            (ARABIC_1500, Decimal("1500"), [NON_ASCII]),
            ("1" + ARABIC_THOUSANDS_SEP + "500", Decimal("1500"), []),
            ("1" + ARABIC_DECIMAL_SEP + "50", Decimal("1.50"), []),
            ("１５００", Decimal("1500"), []),     # full-width, NFKC folds these
            # --- OCR letter-for-digit substitution -----------------------
            ("Rs. l,50O", Decimal("1500"), [GLYPH]),
            ("Rs. I5OO", Decimal("1500"), [GLYPH]),
            ("RS. 1500", Decimal("1500"), []),                    # the S of RS must survive
            # --- separator ambiguity ------------------------------------
            ("1.500", Decimal("1500"), [AMBIG]),
            ("1.500.000", Decimal("1500000"), [AMBIG]),
            ("1,50", Decimal("1.50"), []),                        # decimal comma
            ("1.500,75", Decimal("1500.75"), []),                 # European mixed
            ("1,500.75", Decimal("1500.75"), []),                 # Anglo mixed
        ],
    )
    def test_table(self, raw, value, notes):
        parsed, got_notes = parse_amount_text(raw)
        assert parsed == value
        assert got_notes == notes

    def test_ambiguity_is_reported_not_swallowed(self):
        # "1.500" is genuinely undecidable; the engine has to hear about it.
        _, notes = parse_amount_text("1.500")
        assert AMBIG in notes

    def test_a_clean_amount_carries_no_notes(self):
        assert parse_amount_text("Rs. 1,500")[1] == []

    @pytest.mark.parametrize("raw", ["", "Rs.", "no digits here", "---", "/-"])
    def test_unreadable_amounts_raise(self, raw):
        # A missing amount must be a missing field, never a fabricated zero.
        with pytest.raises(ValueError):
            parse_amount_text(raw)

    def test_is_deterministic(self):
        first = parse_amount_text("Rs. l,50O")
        second = parse_amount_text("Rs. l,50O")
        assert first == second


class TestParseAmountMoney:
    def test_converts_to_minor_units_at_the_boundary(self):
        money, notes = parse_amount_money("Rs. 1,500")
        assert money == Money(150_000, "PKR")
        assert notes == ()

    def test_notes_survive_the_conversion(self):
        money, notes = parse_amount_money("Rs. l,50O")
        assert money == Money(150_000)
        assert notes == (GLYPH,)

    def test_paisa_precision(self):
        money, _ = parse_amount_money("Rs 1,234.56")
        assert money.minor == 123_456


class TestFolding:
    def test_fold_digits_reports_change(self):
        assert fold_digits(ARABIC_1500) == ("1500", True)
        assert fold_digits("1500") == ("1500", False)

    def test_nfkc_collapses_whitespace_and_compatibility_forms(self):
        assert nfkc("  Rs.  1,500  ") == "Rs. 1,500"

    def test_nfkc_does_not_fold_arabic_indic_digits(self):
        # Documented here because the opposite is widely (and wrongly) assumed.
        assert nfkc(ARABIC_1500) == ARABIC_1500


class TestNormalizeName:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            # --- plain -------------------------------------------------
            ("Ali Khan", ("ali", "khan")),
            ("ALI KHAN", ("ali", "khan")),
            ("  ali   khan ", ("ali", "khan")),
            ("Ali-Khan", ("ali", "khan")),
            ("M.Ali", ("m", "ali")),
            ("M. Ali", ("m", "ali")),
            # --- honorifics stripped ------------------------------------
            ("Mr. Ali Khan", ("ali", "khan")),
            ("Mrs Ayesha Bibi", ("ayesha", "bibi")),
            ("Dr Muhammad Ali", ("muhammad", "ali")),
            ("Prof. Ahmed Raza", ("ahmad", "raza")),
            ("Engr. Bilal Ahmed", ("bilal", "ahmad")),
            ("Hafiz Abdul Rehman", ("abdul", "rehman")),
            ("Haji Muhammad Yousuf", ("muhammad", "yousuf")),
            ("Janab Ali Raza", ("ali", "raza")),
            ("Mohtarma Fatima", ("fatima",)),
            # --- real name components that must NOT be stripped ---------
            ("Syed Ali Shah", ("syed", "ali", "shah")),
            ("Khan Muhammad Aslam", ("khan", "muhammad", "aslam")),
            ("Chaudhry Nisar", ("chaudhry", "nisar")),
            ("Malik Riaz", ("malik", "riaz")),
            ("Mian Muhammad Nawaz", ("mian", "muhammad", "nawaz")),
            ("Sheikh Rasheed", ("sheikh", "rasheed")),
            ("Mirza Baig", ("mirza", "baig")),
            # --- transliteration families -------------------------------
            ("Mohammad Ali", ("muhammad", "ali")),
            ("Mohammed Ali", ("muhammad", "ali")),
            ("Muhammed Ali", ("muhammad", "ali")),
            ("Mohd Ali", ("muhammad", "ali")),
            ("Md Ali", ("muhammad", "ali")),
            ("Ahmed Hasan", ("ahmad", "hassan")),
            ("Ahmad Hussein", ("ahmad", "hussain")),
            ("Abd ul Rehman", ("abdul", "rehman")),
            # --- connectors and relations -------------------------------
            ("Ali s/o Hassan", ("ali", "hassan")),
            ("Ayesha d/o Bilal", ("ayesha", "bilal")),
            ("Fatima w/o Ahmed", ("fatima", "ahmad")),
            ("Zainab binte Ali", ("zainab", "ali")),
            # --- wallet chrome ------------------------------------------
            ("Ali Khan - JazzCash Wallet", ("ali", "khan")),
            ("EasyPaisa Account: Ali Raza", ("ali", "raza")),
            ("Ali Traders Pvt Ltd", ("ali", "traders")),
            # --- diacritics and script ----------------------------------
            ("Fátima", ("fatima",)),
            ("Zulqarnain", ("zulqarnain",)),
            ("علی", ()),   # Urdu script alone normalises to nothing
            ("", ()),
            ("123", ()),
        ],
    )
    def test_table(self, raw, expected):
        assert normalize_name(raw) == expected

    def test_honorific_list_excludes_real_name_components(self):
        for token in ("syed", "shah", "khan", "chaudhry", "malik", "mian", "sheikh", "mirza", "baig"):
            assert token not in HONORIFICS

    def test_variant_folding_is_idempotent(self):
        once = normalize_name("Mohammad Ali")
        assert tuple(fold_token(t) for t in once) == once

    def test_a_name_that_is_only_an_honorific_is_empty(self):
        # Empty means "unreadable", which the comparison scores as MISSING.
        assert normalize_name("Mr.") == ()


class TestNormalizeReference:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("TID: 1234-5678", "12345678"),
            ("tid12345678", "12345678"),
            ("1234 5678", "12345678"),
            ("TXN#EP-9001", "EP9001"),
            ("Ref: ABC/123", "ABC123"),
            ("Transaction ID 4455", "4455"),
            ("  ep9001  ", "EP9001"),
        ],
    )
    def test_table(self, raw, expected):
        assert normalize_reference(raw) == expected

    def test_same_id_printed_three_ways_normalises_identically(self):
        forms = ["TID: 1234-5678", "1234 5678", "tid12345678"]
        assert len({normalize_reference(f) for f in forms}) == 1

    def test_confusable_key_survives_ocr_glyph_confusion(self):
        # A misread reference must still retrieve its true transaction.
        assert reference_confusable_key("EP0O12I3") == reference_confusable_key("EPO012l3")

    def test_confusable_key_is_not_equality(self):
        # It is a blocking key: it deliberately loses information.
        assert reference_confusable_key("EPO1") != normalize_reference("EPO1")
