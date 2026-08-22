"""The reference comparison: exact, confusable, truncated, missing, mismatched.

`REF_EXACT` is load-bearing beyond this module - the decision engine's dominance
escape hatch tests for that literal string - so it gets its own contract test.
"""

import pytest

from proofpay.core.compare.levels import always
from proofpay.core.compare.reference import (
    REFERENCE,
    common_suffix_len,
    compare_reference,
    reference_ctx,
)
from proofpay.core.decide.policy import DecisionPolicy

#: The shortest tail that counts as evidence is policy now, not a constant in
#: the comparison module, so every call here has to name the policy it is
#: comparing under - exactly as the engine does.
MIN_PARTIAL = DecisionPolicy().ref_min_partial_len


def level_for(claim_ref, txn_ref) -> str:
    return compare_reference(claim_ref, txn_ref, min_partial_len=MIN_PARTIAL).level_code


class TestLadderStructure:
    def test_level_codes_are_the_published_contract(self):
        assert REFERENCE.codes == (
            "REF_EXACT",
            "REF_CONFUSABLE",
            "REF_SUFFIX",
            "REF_PARTIAL",
            "REF_MISSING",
            "REF_ELSE",
        )

    def test_ref_exact_is_the_top_level_and_keeps_its_exact_spelling(self):
        # The engine looks for this string when deciding that a unique
        # transaction id overrides the ambiguity margin. Renaming it silently
        # disables that escape hatch.
        top = REFERENCE.levels[0]
        assert top.code == "REF_EXACT"
        assert top.score == 1.0

    def test_field_name_and_weight(self):
        assert REFERENCE.field == "reference"
        assert REFERENCE.weight == 1.0

    def test_the_ladder_ends_in_a_real_else(self):
        assert REFERENCE.levels[-1].predicate is always
        assert REFERENCE.levels[-1].code == "REF_ELSE"

    def test_scores_are_non_increasing(self):
        scores = [lvl.score for lvl in REFERENCE.levels]
        assert scores == sorted(scores, reverse=True)


class TestExact:
    @pytest.mark.parametrize(
        ("claim_ref", "txn_ref"),
        [
            ("12345678", "12345678"),
            ("TID: 1234-5678", "tid12345678"),
            ("  1234 5678  ", "12345678"),
            ("Transaction ID: RX9021", "rx9021"),
            ("TXN#RX9021", "RX9021"),
        ],
    )
    def test_formatting_differences_are_not_differences(self, claim_ref, txn_ref):
        outcome = compare_reference(claim_ref, txn_ref, min_partial_len=MIN_PARTIAL)
        assert outcome.level_code == "REF_EXACT"
        assert outcome.score == 1.0

    def test_the_normalised_forms_are_in_the_evidence(self):
        detail = compare_reference("TID: 1234-5678", "tid12345678", min_partial_len=MIN_PARTIAL).detail
        assert detail["left_norm"] == "12345678"
        assert detail["right_norm"] == "12345678"
        assert detail["equal"] is True


class TestConfusable:
    def test_ocr_letter_digit_confusion_scores_below_exact(self):
        # `I23O` is `1230` misread; the same reference, not a matching one.
        outcome = compare_reference("Ref: I23O", "1230", min_partial_len=MIN_PARTIAL)
        assert outcome.level_code == "REF_CONFUSABLE"
        assert outcome.score == 0.90
        assert outcome.detail["equal"] is False

    def test_confusable_never_claims_to_be_exact(self):
        assert level_for("SO12", "5012") == "REF_CONFUSABLE"
        assert level_for("SO12", "5012") != "REF_EXACT"


class TestTruncated:
    @pytest.mark.parametrize(
        ("claim_ref", "txn_ref"),
        [
            ("4821", "99904821"),
            ("TXN 4821", "TID 99904821"),
            ("****4821", "99904821"),
            ("99904821", "4821"),
        ],
    )
    def test_a_receipt_showing_only_the_tail_is_a_suffix_match(self, claim_ref, txn_ref):
        outcome = compare_reference(claim_ref, txn_ref, min_partial_len=MIN_PARTIAL)
        assert outcome.level_code == "REF_SUFFIX"
        assert outcome.score == 0.75
        assert outcome.detail["is_suffix"] is True

    def test_a_tail_shorter_than_the_minimum_is_noise_not_evidence(self):
        assert MIN_PARTIAL == 4
        assert level_for("821", "99904821") == "REF_ELSE"

    def test_two_differently_truncated_ids_sharing_a_tail_are_partial(self):
        outcome = compare_reference("99991234", "88881234", min_partial_len=MIN_PARTIAL)
        assert outcome.level_code == "REF_PARTIAL"
        assert outcome.score == 0.55
        assert outcome.detail["common_suffix_len"] == 4

    def test_a_match_in_the_middle_is_partial_not_suffix(self):
        outcome = compare_reference("1234", "AB1234CD", min_partial_len=MIN_PARTIAL)
        assert outcome.level_code == "REF_PARTIAL"
        assert outcome.detail["contains"] is True
        assert outcome.detail["is_suffix"] is False

    def test_common_suffix_len_counts_from_the_tail(self):
        assert common_suffix_len("99904821", "4821") == 4
        assert common_suffix_len("4821XX", "4821") == 0
        assert common_suffix_len("", "4821") == 0


class TestMissing:
    @pytest.mark.parametrize(
        ("claim_ref", "txn_ref"),
        [
            (None, "12345678"),
            ("12345678", None),
            (None, None),
            ("", "12345678"),
            ("   ", "12345678"),
            ("TID:", "12345678"),  # a label with no id behind it
        ],
    )
    def test_nothing_to_compare(self, claim_ref, txn_ref):
        outcome = compare_reference(claim_ref, txn_ref, min_partial_len=MIN_PARTIAL)
        assert outcome.level_code == "REF_MISSING"
        assert outcome.is_missing
        assert outcome.score == 0.0

    def test_two_absent_references_are_never_an_exact_match(self):
        # Both normalise to "", and an unguarded equality test would call that
        # a perfect transaction-id match - the worst false positive available.
        assert level_for(None, None) != "REF_EXACT"
        assert reference_ctx(None, None, min_partial_len=MIN_PARTIAL)["equal"] is False
        assert reference_ctx("TID:", "REF:", min_partial_len=MIN_PARTIAL)["equal"] is False


class TestMismatch:
    @pytest.mark.parametrize(
        ("claim_ref", "txn_ref"),
        [
            ("12345678", "87654321"),
            ("AB1234CD", "XX1234YY"),  # shared middle, but neither contains the other
            ("RX9021", "RX9022"),
            ("1234", "5678"),
        ],
    )
    def test_different_ids_do_not_match(self, claim_ref, txn_ref):
        outcome = compare_reference(claim_ref, txn_ref, min_partial_len=MIN_PARTIAL)
        assert outcome.level_code == "REF_ELSE"
        assert outcome.score == 0.0
        assert outcome.is_missing is False


class TestOrdering:
    def test_stronger_evidence_always_scores_higher(self):
        exact = compare_reference("99904821", "99904821", min_partial_len=MIN_PARTIAL).score
        confusable = compare_reference("999O4821", "99904821", min_partial_len=MIN_PARTIAL).score
        suffix = compare_reference("4821", "99904821", min_partial_len=MIN_PARTIAL).score
        partial = compare_reference("77704821", "99904821", min_partial_len=MIN_PARTIAL).score
        mismatch = compare_reference("11112222", "99904821", min_partial_len=MIN_PARTIAL).score
        assert exact > confusable > suffix > partial > mismatch

    def test_evaluation_is_total_for_arbitrary_inputs(self):
        # Totality is structural, but the ladder is also the last thing standing
        # between a garbled OCR string and an unexplained decision.
        for claim_ref in (None, "", "??", "0", "A" * 64, "1234-5678"):
            for txn_ref in (None, "", "12345678", "A" * 64):
                assert compare_reference(claim_ref, txn_ref, min_partial_len=MIN_PARTIAL).level_code in REFERENCE.codes
