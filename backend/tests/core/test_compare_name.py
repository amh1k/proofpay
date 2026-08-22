"""Tests for the sender-name comparison.

Every assertion names a LEVEL CODE. The codes are the stable machine
identifiers that reach golden files, the database and the UI; a test that only
checked a score would pass while the explanation shown to a merchant silently
became wrong.
"""

import pytest

from proofpay.core.compare.levels import (
    Agreement,
    Comparison,
    Level,
    always,
    else_level,
)
from proofpay.core.compare.name import (
    COMMON_NAME_TOKENS,
    SENDER_NAME,
    MaskToken,
    NameThresholds,
    build_name_idf,
    compare_name,
    mask_consistency,
    mask_tokens,
    name_comparison,
    name_metrics,
    name_observations,
    seed_idf,
    token_alignment,
)
from proofpay.core.normalize import normalize_name_many
from proofpay.core.reasons import ObservationCode

# The values the design guide recommends. In production these come from
# DecisionPolicy; the tests pin them so a policy change cannot silently
# reinterpret these cases.
T = NameThresholds(strong=0.92, initials=0.80, pair_min=0.70, common_idf=0.30)
FLOOR = 0.15
IDF = seed_idf(FLOOR)


def level_of(claim: str | None, truth: str | None) -> str:
    return compare_name(claim, truth, idf=IDF, thresholds=T).level_code


# ---------------------------------------------------------------------------
# The ladder itself
# ---------------------------------------------------------------------------

def test_level_codes_are_the_documented_ladder_in_order():
    assert SENDER_NAME.codes == (
        "NAME_EXACT",
        "NAME_STRONG",
        "NAME_MASK_OK",
        "NAME_INITIALS",
        "NAME_PARTIAL",
        "NAME_COMMON_ONLY",
        "NAME_MISSING",
        "NAME_ELSE",
    )


def test_scores_are_non_increasing_and_the_ladder_ends_in_a_total_else():
    scores = [lvl.score for lvl in SENDER_NAME.levels]
    assert scores == [1.00, 0.90, 0.85, 0.80, 0.55, 0.20, 0.00, 0.00]
    assert scores == sorted(scores, reverse=True)
    assert SENDER_NAME.levels[-1].code == "NAME_ELSE"
    assert SENDER_NAME.levels[-1].predicate is always


def test_the_guides_ordering_would_be_rejected_by_the_constructor():
    """The ordering problem section 2.2 flags is a construction-time error.

    Mask-before-strong is why the ladder guards NAME_STRONG instead of
    reordering; this test is the reason that decision could not be made
    differently.
    """
    with pytest.raises(ValueError, match="most->least similar"):
        Comparison(
            field="sender_name",
            levels=(
                Level(
                    "NAME_MASK_OK",
                    "Consistent with masked name",
                    0.85,
                    lambda a, b, c: False,
                    Agreement.AGREE,
                ),
                Level(
                    "NAME_STRONG",
                    "Strong match",
                    0.90,
                    lambda a, b, c: False,
                    Agreement.AGREE,
                ),
                else_level("NAME_ELSE", "No name match"),
            ),
        )


def test_the_ladder_is_reusable_for_other_name_fields():
    receiver = name_comparison("receiver_name", weight=0.5)
    assert receiver.field == "receiver_name"
    assert receiver.weight == 0.5
    assert receiver.codes == SENDER_NAME.codes


# ---------------------------------------------------------------------------
# The required scenarios, one per level
# ---------------------------------------------------------------------------

def test_exact_match_on_a_distinctive_name():
    outcome = compare_name("Zulqarnain Haider", "Zulqarnain Haider", idf=IDF, thresholds=T)
    assert outcome.level_code == "NAME_EXACT"
    assert outcome.score == 1.00
    assert outcome.detail["token_score"] == 1.0
    assert not outcome.is_missing


def test_exact_match_survives_transliteration_and_an_honorific():
    # Mohd -> muhammad, "Mr." dropped: the same customer, written two ways.
    assert level_of("Mr. Mohd Zulqarnain", "Muhammad Zulqarnain") == "NAME_EXACT"


def test_muhammad_ali_versus_m_ali_is_an_initials_match():
    outcome = compare_name("Muhammad Ali", "M. Ali", idf=IDF, thresholds=T)
    assert outcome.level_code == "NAME_INITIALS"
    assert outcome.score == 0.80
    assert outcome.detail["initials_compatible"] is True
    assert outcome.detail["token_score"] == pytest.approx(0.95)
    # An expanded initial is a structural agreement, not a spelling one, so it
    # must not be sold to the merchant as "minor spelling difference".
    assert outcome.detail["token_score"] >= T.strong


def test_a_masked_receipt_name_is_its_own_level():
    outcome = compare_name("Muhammad Ali", "MUHAMMAD A***", idf=IDF, thresholds=T)
    assert outcome.level_code == "NAME_MASK_OK"
    assert outcome.score == 0.85
    assert outcome.detail["mask_present"] is True
    assert outcome.detail["mask_consistent"] is True
    assert ObservationCode.NAME_MASKED in name_observations(outcome.detail)


def test_a_mask_whose_visible_prefix_contradicts_the_ledger_is_not_mask_ok():
    # "B***" cannot be "Zulqarnain"; only the common given name aligns.
    outcome = compare_name("Muhammad Zulqarnain", "MUHAMMAD B***", idf=IDF, thresholds=T)
    assert outcome.detail["mask_consistent"] is False
    assert outcome.level_code == "NAME_COMMON_ONLY"


def test_two_different_people_who_share_only_muhammad():
    outcome = compare_name("Muhammad Ali", "Muhammad Usman", idf=IDF, thresholds=T)
    assert outcome.level_code == "NAME_COMMON_ONLY"
    assert outcome.score == 0.20
    assert outcome.detail["idf_weighted_score"] < T.common_idf
    assert ObservationCode.NAME_COMMON_TOKENS_ONLY in name_observations(outcome.detail)


def test_two_identical_very_common_names_are_not_sold_as_an_exact_match():
    """The single most likely way this engine matches the wrong transaction.

    Two customers both called Muhammad Ali agree on every token, and that
    agreement is worth almost nothing. NAME_EXACT at 1.00 would hand a
    wrong-transaction match a confident explanation.
    """
    outcome = compare_name("Muhammad Ali", "Muhammad Ali", idf=IDF, thresholds=T)
    assert outcome.level_code == "NAME_COMMON_ONLY"
    assert outcome.detail["token_score"] == 1.0
    assert outcome.detail["idf_weighted_score"] == pytest.approx(FLOOR)


def test_one_shared_token_is_partial_or_common_only_purely_because_of_idf():
    """Identical match *shape*, opposite verdicts. This is what IDF buys."""
    common = compare_name("Muhammad Ali", "Muhammad Usman", idf=IDF, thresholds=T)
    rare = compare_name("Zulqarnain Haider", "Zulqarnain Butt", idf=IDF, thresholds=T)
    assert common.detail["token_score"] == rare.detail["token_score"] == 0.5
    assert common.level_code == "NAME_COMMON_ONLY"
    assert rare.level_code == "NAME_PARTIAL"
    assert rare.score > common.score


def test_minor_spelling_differences_are_a_strong_match():
    outcome = compare_name("Zulqarnain Haider", "Zulqarnian Hayder", idf=IDF, thresholds=T)
    assert outcome.level_code == "NAME_STRONG"
    assert outcome.score == 0.90
    assert outcome.detail["token_score"] >= T.strong


def test_token_order_does_not_break_a_match():
    # Receipts and ledgers disagree about which component comes first.
    assert level_of("Ali Muhammad Zulqarnain", "Muhammad Zulqarnain Ali") == "NAME_STRONG"


@pytest.mark.parametrize(
    "claim, truth",
    [
        (None, "Muhammad Ali"),
        ("Muhammad Ali", None),
        ("", "Muhammad Ali"),
        ("   ", "Muhammad Ali"),
        ("محمد", "Muhammad Ali"),  # Urdu script: nothing to compare
        ("Mr.", "Muhammad Ali"),                        # an honorific is not a name
    ],
)
def test_unreadable_names_are_missing_not_mismatched(claim, truth):
    outcome = compare_name(claim, truth, idf=IDF, thresholds=T)
    assert outcome.level_code == "NAME_MISSING"
    assert outcome.score == 0.0
    assert outcome.is_missing is True


def test_a_clear_non_match_falls_to_the_else_level():
    outcome = compare_name("Ayesha Siddiqui", "Bilal Tanoli", idf=IDF, thresholds=T)
    assert outcome.level_code == "NAME_ELSE"
    assert outcome.score == 0.0
    assert outcome.is_missing is False
    assert outcome.detail["pair_count"] == 0


def test_else_and_missing_score_the_same_but_are_told_apart_by_the_code():
    """Zero evidence either way; only `is_missing` may drive coverage."""
    mismatch = compare_name("Ayesha Siddiqui", "Bilal Tanoli", idf=IDF, thresholds=T)
    missing = compare_name(None, "Bilal Tanoli", idf=IDF, thresholds=T)
    assert mismatch.score == missing.score == 0.0
    assert (mismatch.is_missing, missing.is_missing) == (False, True)


# ---------------------------------------------------------------------------
# Token alignment
# ---------------------------------------------------------------------------

def test_alignment_pairs_the_initial_with_the_full_token():
    metrics = token_alignment(("muhammad", "ali"), ("m", "ali"), IDF, pair_min=T.pair_min)
    assert metrics["pairs"] == (("ali", "ali", 1.0), ("muhammad", "m", 0.90))
    assert metrics["initials_compatible"] is True
    assert metrics["token_score"] == pytest.approx(0.95)


def test_alignment_refuses_a_pairing_below_pair_min():
    """`ali`/`zulqarnain` sits at JW 0.46. Pairing them would both inflate the
    score and consume the token the real match needed."""
    metrics = token_alignment(("ali",), ("zulqarnain",), IDF, pair_min=T.pair_min)
    assert metrics["pairs"] == ()
    assert metrics["token_score"] == 0.0
    assert metrics["unmatched_truth"] == ("zulqarnain",)


def test_alignment_does_not_let_a_subset_score_a_full_match():
    """The trap `fuzz.token_set_ratio` falls into: 100 for any subset."""
    metrics = token_alignment(
        ("muhammad",), ("muhammad", "ali", "khan"), IDF, pair_min=T.pair_min
    )
    assert metrics["token_score"] == pytest.approx(1 / 3)


def test_alignment_is_deterministic_across_input_order():
    a = token_alignment(("ali", "muhammad"), ("m", "ali"), IDF, pair_min=T.pair_min)
    b = token_alignment(("muhammad", "ali"), ("ali", "m"), IDF, pair_min=T.pair_min)
    assert a["pairs"] == b["pairs"]


def test_weighted_score_separates_rare_agreement_from_common_agreement():
    rare = token_alignment(
        ("zulqarnain", "tanoli"), ("zulqarnain", "tanoli"), IDF, pair_min=T.pair_min
    )
    common = token_alignment(
        ("muhammad", "ali"), ("muhammad", "ali"), IDF, pair_min=T.pair_min
    )
    assert rare["token_score"] == common["token_score"] == 1.0
    assert rare["idf_weighted_score"] == 1.0
    assert common["idf_weighted_score"] == pytest.approx(FLOOR)


# ---------------------------------------------------------------------------
# IDF
# ---------------------------------------------------------------------------

def test_seed_idf_floors_every_common_token():
    seed = seed_idf(FLOOR)
    assert set(seed) == set(COMMON_NAME_TOKENS)
    assert all(value == FLOOR for value in seed.values())


def test_build_idf_learns_rarity_from_the_feed():
    feed = ["Muhammad Ali"] * 15 + ["Muhammad Usman"] * 4 + ["Zulqarnain Tanoli"]
    idf = build_name_idf(normalize_name_many(feed), floor=FLOOR)
    assert idf["zulqarnain"] > 0.7
    assert idf["tanoli"] > 0.7
    assert idf["usman"] < idf["zulqarnain"]


def test_build_idf_pins_common_tokens_even_when_the_feed_disagrees():
    """A merchant whose only Muhammad is one transaction has not discovered
    that Muhammad is rare."""
    feed = ["Zulqarnain Tanoli"] * 9 + ["Muhammad Ali"]
    idf = build_name_idf(normalize_name_many(feed), floor=FLOOR)
    assert idf["muhammad"] == FLOOR
    assert idf["ali"] == FLOOR


def test_build_idf_falls_back_to_the_seed_when_the_feed_is_too_small():
    # log(1) == 0; a single document carries no discrimination information.
    assert build_name_idf(normalize_name_many(["Muhammad Ali"]), floor=FLOOR) == seed_idf(FLOOR)
    assert build_name_idf([], floor=FLOOR) == seed_idf(FLOOR)


def test_an_unknown_token_is_treated_as_distinctive():
    metrics = token_alignment(("tanoli",), ("tanoli",), {}, pair_min=T.pair_min)
    assert metrics["idf_weighted_score"] == 1.0


# ---------------------------------------------------------------------------
# Masks
# ---------------------------------------------------------------------------

def test_mask_tokens_keeps_the_visible_prefix_and_counts_what_is_hidden():
    tokens = mask_tokens("MUHAMMAD A***")
    assert [(t.text, t.masked, t.hidden) for t in tokens] == [
        ("muhammad", False, 0),
        ("a", True, 3),
    ]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("MUHAMMAD ****", [("muhammad", False), ("", True)]),
        # A visible prefix is kept as printed: "moh" is not a known variant of
        # anything, so folding must not invent one.
        ("MOH*** ZULQARNAIN", [("moh", True), ("zulqarnain", False)]),
        ("Ali XXXX", [("ali", False), ("", True)]),
        ("Xavier Ali", [("xavier", False), ("ali", False)]),  # one x is a letter
    ],
)
def test_mask_token_shapes(raw, expected):
    assert [(t.text, t.masked) for t in mask_tokens(raw)] == expected


def test_a_masked_prefix_is_matched_against_the_unfolded_spelling():
    # "moh" prefixes "mohammad" but not its canonical fold "muhammad".
    assert level_of("Mohammad Zulqarnain", "MOH*** ZULQARNAIN") == "NAME_MASK_OK"


def test_a_fully_hidden_token_is_a_wildcard_not_evidence():
    wildcard = mask_tokens("****")[0]
    assert wildcard.is_wildcard is True
    both_hidden = mask_consistency(mask_tokens("**** ****"), mask_tokens("Muhammad Ali"), strong=T.strong)
    assert both_hidden["mask_present"] is True
    assert both_hidden["mask_consistent"] is False  # consistent, but evidence for nothing


def test_a_mask_beside_a_readable_token_is_consistent():
    result = mask_consistency(
        mask_tokens("Muhammad ****"), mask_tokens("Muhammad Zulqarnain"), strong=T.strong
    )
    assert result["mask_consistent"] is True
    assert result["mask_hidden_chars"] == 4


def test_mask_consistency_is_false_when_no_mask_is_involved():
    result = mask_consistency(
        mask_tokens("Muhammad Ali"), mask_tokens("Muhammad Ali"), strong=T.strong
    )
    assert result == {
        "mask_present": False,
        "mask_consistent": False,
        "mask_hidden_chars": 0,
        "mask_pairs": (),
    }


def test_a_mask_on_a_name_that_could_not_be_read_stays_missing():
    outcome = compare_name("Muhammad Ali", "****", idf=IDF, thresholds=T)
    assert outcome.level_code == "NAME_MISSING"
    assert outcome.detail["mask_consistent"] is False


def test_mask_token_is_a_frozen_value_object():
    token = MaskToken(text="a", raw="a", masked=True, hidden=3)
    with pytest.raises(AttributeError):
        token.masked = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Metric bundle and thresholds
# ---------------------------------------------------------------------------

def test_the_detail_records_the_thresholds_that_were_applied():
    detail = compare_name("Muhammad Ali", "M. Ali", idf=IDF, thresholds=T).detail
    assert detail["t_strong"] == T.strong
    assert detail["t_initials"] == T.initials
    assert detail["t_pair_min"] == T.pair_min
    assert detail["t_common_idf"] == T.common_idf
    assert detail["claim_tokens"] == ("muhammad", "ali")
    assert detail["truth_tokens"] == ("m", "ali")


def test_metrics_are_reproducible():
    args = ("Muhammad Ali", "MUHAMMAD A***")
    first = name_metrics(*args, idf=IDF, thresholds=T)
    second = name_metrics(*args, idf=IDF, thresholds=T)
    assert first == second


def test_a_policy_change_moves_the_level_without_touching_this_module():
    """Thresholds live in policy: the same names, a stricter ladder, a new row."""
    strict = NameThresholds(strong=0.99, initials=0.99, pair_min=0.99, common_idf=0.30)
    assert level_of("Muhammad Ali", "M. Ali") == "NAME_INITIALS"
    assert (
        compare_name("Muhammad Ali", "M. Ali", idf=IDF, thresholds=strict).level_code
        == "NAME_COMMON_ONLY"
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"strong": 1.5, "initials": 0.80, "pair_min": 0.70, "common_idf": 0.30},
        {"strong": 0.92, "initials": 0.80, "pair_min": 0.70, "common_idf": -0.1},
        {"strong": 1, "initials": 0.80, "pair_min": 0.70, "common_idf": 0.30},
        {"strong": 0.70, "initials": 0.80, "pair_min": 0.92, "common_idf": 0.30},
    ],
)
def test_nonsense_thresholds_are_rejected_at_construction(kwargs):
    with pytest.raises(ValueError):
        NameThresholds(**kwargs)


def test_no_observations_for_a_clean_distinctive_match():
    detail = compare_name("Zulqarnain Tanoli", "Zulqarnain Tanoli", idf=IDF, thresholds=T).detail
    assert name_observations(detail) == ()
