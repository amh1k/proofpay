"""The comparison-level machinery: ordering, uniqueness, totality, evaluation.

These invariants are the reason a `KeyError` can never reach an audit trail.
"""

from dataclasses import FrozenInstanceError

import pytest

from proofpay.core.compare.levels import (
    Comparison,
    FieldOutcome,
    Level,
    always,
    default_metrics,
    else_level,
)


def _score_at_least(threshold: float):
    """A predicate in the shape every real comparison uses: read a pre-computed
    metric out of ctx and apply the inclusive `>=` convention."""
    return lambda a, b, ctx: ctx["score"] >= threshold


EXACT = Level("X_EXACT", "Exact match", 1.0, lambda a, b, ctx: a == b)
STRONG = Level("X_STRONG", "Strong match", 0.9, _score_at_least(0.9))
WEAK = Level("X_WEAK", "Weak match", 0.5, _score_at_least(0.5))
ELSE = else_level("X_ELSE", "No match")

DEMO = Comparison(field="demo", levels=(EXACT, STRONG, WEAK, ELSE))


class TestLevel:
    def test_code_and_label_are_separate(self):
        # The code is a contract; the label is UI text and may be reworded.
        assert EXACT.code == "X_EXACT"
        assert EXACT.label == "Exact match"

    def test_empty_code_is_rejected(self):
        with pytest.raises(ValueError):
            Level("", "no code", 1.0, always)

    @pytest.mark.parametrize("score", [-0.1, 1.1])
    def test_score_must_be_a_similarity(self, score):
        with pytest.raises(ValueError):
            Level("X", "out of range", score, always)

    def test_is_frozen(self):
        with pytest.raises(FrozenInstanceError):
            EXACT.score = 0.1  # type: ignore[misc]


class TestComparisonInvariants:
    def test_empty_levels_rejected(self):
        with pytest.raises(ValueError, match="no levels"):
            Comparison(field="demo", levels=())

    def test_non_monotonic_scores_rejected(self):
        # A lower level scoring higher makes the explanation contradict the number.
        with pytest.raises(ValueError, match="non-increasing"):
            Comparison(field="demo", levels=(WEAK, STRONG, ELSE))

    def test_equal_adjacent_scores_are_allowed(self):
        twin = Level("X_TWIN", "Also strong", 0.9, _score_at_least(0.9))
        assert Comparison(field="demo", levels=(STRONG, twin, ELSE)).codes == (
            "X_STRONG",
            "X_TWIN",
            "X_ELSE",
        )

    def test_duplicate_codes_rejected(self):
        clone = Level("X_STRONG", "Different label, same code", 0.7, always)
        with pytest.raises(ValueError, match="duplicate level codes"):
            Comparison(field="demo", levels=(STRONG, clone))

    def test_missing_else_rejected(self):
        # Totality is structural: the last level must be the exported `always`.
        with pytest.raises(ValueError, match="catch-all ELSE"):
            Comparison(field="demo", levels=(EXACT, STRONG))

    def test_inline_true_lambda_is_not_accepted_as_an_else(self):
        # `lambda a, b, c: True` is total in fact but not checkable; the error
        # message points the author at `else_level` / `always`.
        sneaky = Level("X_SNEAKY", "Catch all", 0.0, lambda a, b, ctx: True)
        with pytest.raises(ValueError, match="else_level"):
            Comparison(field="demo", levels=(EXACT, sneaky))

    def test_negative_weight_rejected(self):
        with pytest.raises(ValueError):
            Comparison(field="demo", levels=(ELSE,), weight=-1.0)

    def test_default_weight_is_one(self):
        assert DEMO.weight == 1.0


class TestEvaluate:
    @pytest.mark.parametrize(
        "left,right,score,expected_code,expected_score",
        [
            ("a", "a", 0.0, "X_EXACT", 1.0),      # equality wins before any metric
            ("a", "b", 0.95, "X_STRONG", 0.9),
            ("a", "b", 0.90, "X_STRONG", 0.9),    # inclusive at the threshold
            ("a", "b", 0.8999, "X_WEAK", 0.5),
            ("a", "b", 0.50, "X_WEAK", 0.5),      # inclusive again
            ("a", "b", 0.4999, "X_ELSE", 0.0),
            ("a", "b", 0.0, "X_ELSE", 0.0),
        ],
    )
    def test_first_match_wins(self, left, right, score, expected_code, expected_score):
        outcome = DEMO.evaluate(left, right, {"score": score})
        assert outcome.level_code == expected_code
        assert outcome.score == expected_score
        assert outcome.field == "demo"

    def test_outcome_carries_the_label_for_the_ui(self):
        assert DEMO.evaluate("a", "b", {"score": 0.95}).label == "Strong match"

    def test_detail_carries_the_raw_metrics(self):
        outcome = DEMO.evaluate("a", "b", {"score": 0.95, "pairs": [("a", "b")]})
        assert outcome.detail["score"] == 0.95
        assert outcome.detail["pairs"] == [("a", "b")]

    def test_detail_is_a_read_only_snapshot(self):
        ctx = {"score": 0.95}
        outcome = DEMO.evaluate("a", "b", ctx)
        ctx["score"] = 0.1
        assert outcome.detail["score"] == 0.95
        with pytest.raises(TypeError):
            outcome.detail["score"] = 0.2  # type: ignore[index]

    def test_exactly_one_level_fires_for_any_score(self):
        for hundredth in range(101):
            outcome = DEMO.evaluate("a", "b", {"score": hundredth / 100})
            assert outcome.level_code in DEMO.codes

    def test_else_fires_when_ctx_is_empty(self):
        # An ELSE that depended on ctx would raise KeyError here.
        total = Comparison(field="demo", levels=(else_level("D_ELSE", "Nothing"),))
        assert total.evaluate(None, None).level_code == "D_ELSE"

    def test_a_custom_metrics_function_replaces_the_detail(self):
        comparison = Comparison(
            field="demo",
            levels=(ELSE,),
            metrics=lambda a, b, ctx: {"left": a, "right": b},
        )
        assert comparison.evaluate("x", "y", {"score": 1.0}).detail == {"left": "x", "right": "y"}

    def test_default_metrics_copies_ctx(self):
        assert dict(default_metrics(None, None, {"a": 1})) == {"a": 1}


class TestFieldOutcome:
    def test_missing_is_detected_by_suffix_convention(self):
        missing = FieldOutcome(
            field="sender_name", level_code="NAME_MISSING", label="Not readable", score=0.0
        )
        present = FieldOutcome(
            field="sender_name", level_code="NAME_EXACT", label="Exact match", score=1.0
        )
        assert missing.is_missing is True
        assert present.is_missing is False

    def test_a_level_code_ending_in_else_is_not_missing(self):
        # "we looked and disagreed" is evidence; "we could not read it" is not.
        outcome = FieldOutcome(field="x", level_code="NAME_ELSE", label="No match", score=0.0)
        assert outcome.is_missing is False

    def test_is_frozen(self):
        outcome = FieldOutcome(field="x", level_code="X_ELSE", label="No match", score=0.0)
        with pytest.raises(FrozenInstanceError):
            outcome.score = 1.0  # type: ignore[misc]


def test_always_is_unconditional():
    assert always(None, None, {}) is True
    assert always("x", 3, {"anything": 1}) is True
