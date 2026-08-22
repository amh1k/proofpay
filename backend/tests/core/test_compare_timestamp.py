"""The timestamp comparison: the decay curve, the ladder over it, and the
guarantee that a closer time never scores worse than a further one.

Every case fixes an exact level code, because the level code is what the rule
table and the golden files consume - a test that only asserts "it matched" would
let the ladder rewire itself silently.
"""

from datetime import datetime, timedelta

import pytest

from proofpay.core.compare.decay import exponential, gauss
from proofpay.core.compare.levels import always
from proofpay.core.compare.timestamp import (
    MAX_HOUR_ARTIFACT,
    TIMESTAMP,
    TimestampParams,
    compare_timestamp,
    timestamp_ctx,
    timestamp_observations,
    window_gap_s,
)
from proofpay.core.decide.policy import DecisionPolicy
from proofpay.core.reasons import ObservationCode
from proofpay.core.timex import (
    GRANULARITY_DAY,
    GRANULARITY_MINUTE,
    PKT,
    UTC,
    ClaimedInstant,
)

# The parameters suggested in the design guide, which the shipped DecisionPolicy
# also carries. Repeated here so a policy change cannot silently rewrite what
# these tests are asserting about the ladder. The three `sim_*` cut-points are
# part of that bundle now rather than module constants: they carve this curve
# into rungs, which moves verdicts, so they are policy and are fingerprinted.
PARAMS = TimestampParams(
    offset_s=120.0,
    scale_s=900.0,
    offset_s_date_inferred=21_600.0,
    scale_s_date_inferred=43_200.0,
    hour_artifact_tol_s=90.0,
    sim_tight=0.98,
    sim_close=0.80,
    sim_loose=0.40,
)

SIM_TIGHT = PARAMS.sim_tight
SIM_CLOSE = PARAMS.sim_close
SIM_LOOSE = PARAMS.sim_loose

TXN_AT = datetime(2026, 3, 4, 15, 30, 0, tzinfo=UTC)


def claim_at(seconds: float, **kwargs) -> ClaimedInstant:
    """A receipt reading `seconds` away from the ledger transaction."""
    return ClaimedInstant(resolved_utc=TXN_AT + timedelta(seconds=seconds), **kwargs)


def level_for(seconds: float, **kwargs) -> str:
    return compare_timestamp(claim_at(seconds, **kwargs), TXN_AT, PARAMS).level_code


class TestDecayCurve:
    def test_inside_the_offset_is_full_similarity(self):
        assert gauss(90.0, 120.0, 900.0) == 1.0
        assert gauss(-120.0, 120.0, 900.0) == 1.0

    def test_half_similarity_lands_exactly_at_offset_plus_scale(self):
        # This is the property that makes `scale` explainable in a design
        # review: it is the half-similarity distance.
        assert gauss(1020.0, 120.0, 900.0) == pytest.approx(0.5)
        assert exponential(1020.0, 120.0, 900.0) == pytest.approx(0.5)

    def test_gauss_punishes_the_far_tail_harder_than_exponential(self):
        assert gauss(3000.0, 120.0, 900.0) < exponential(3000.0, 120.0, 900.0)

    def test_curve_is_monotonically_non_increasing(self):
        sims = [gauss(float(d), 120.0, 900.0) for d in range(0, 5_000, 25)]
        assert sims == sorted(sims, reverse=True)

    @pytest.mark.parametrize(
        ("offset", "scale"),
        [(-1.0, 900.0), (120.0, 0.0), (120.0, -900.0)],
    )
    def test_impossible_parameters_are_rejected(self, offset, scale):
        with pytest.raises(ValueError):
            gauss(10.0, offset, scale)


class TestLadderStructure:
    def test_level_codes_are_the_published_contract(self):
        assert TIMESTAMP.codes == (
            "TS_TIGHT",
            "TS_CLOSE",
            "TS_DATE_ONLY",
            "TS_LOOSE",
            "TS_HOUR_ART",
            "TS_MISSING",
            "TS_ELSE",
        )

    def test_field_name_and_weight(self):
        """The ladder owns the field; `DecisionPolicy` owns what it is worth.

        A field weight steers every aggregate it feeds, so it is a policy value
        and reaches the fingerprint. What is asserted here is that this module
        no longer holds a second, unversioned copy of it.
        """
        assert TIMESTAMP.field == "timestamp"
        assert DecisionPolicy().field_weights()["timestamp"] == 0.8

    def test_the_ladder_ends_in_a_real_else(self):
        assert TIMESTAMP.levels[-1].predicate is always
        assert TIMESTAMP.levels[-1].score == 0.0

    def test_scores_are_non_increasing(self):
        scores = [lvl.score for lvl in TIMESTAMP.levels]
        assert scores == sorted(scores, reverse=True)
        assert scores[0] == 1.0


class TestPreciseReadings:
    def test_same_instant_is_tight_with_full_similarity(self):
        outcome = compare_timestamp(claim_at(0), TXN_AT, PARAMS)
        assert outcome.level_code == "TS_TIGHT"
        assert outcome.score == 1.0
        assert outcome.detail["sim"] == 1.0
        assert outcome.detail["delta_s"] == 0.0

    def test_one_minute_apart_is_still_tight(self):
        # A minute is inside the free window: clock skew, not disagreement.
        outcome = compare_timestamp(claim_at(60), TXN_AT, PARAMS)
        assert outcome.level_code == "TS_TIGHT"
        assert outcome.detail["sim"] == 1.0
        assert outcome.detail["delta_s"] == 60.0

    def test_three_minutes_apart_is_tight_but_no_longer_perfect(self):
        outcome = compare_timestamp(claim_at(180), TXN_AT, PARAMS)
        assert outcome.level_code == "TS_TIGHT"
        assert SIM_TIGHT <= outcome.detail["sim"] < 1.0

    @pytest.mark.parametrize("seconds", [300, 480, 600, -600])
    def test_five_to_ten_minutes_is_close(self, seconds):
        outcome = compare_timestamp(claim_at(seconds), TXN_AT, PARAMS)
        assert outcome.level_code == "TS_CLOSE"
        assert SIM_CLOSE <= outcome.detail["sim"] < SIM_TIGHT

    def test_the_half_similarity_distance_is_loose(self):
        outcome = compare_timestamp(claim_at(1020), TXN_AT, PARAMS)
        assert outcome.level_code == "TS_LOOSE"
        assert outcome.detail["sim"] == pytest.approx(0.5)

    def test_half_an_hour_does_not_correspond(self):
        outcome = compare_timestamp(claim_at(1800), TXN_AT, PARAMS)
        assert outcome.level_code == "TS_ELSE"
        assert outcome.score == 0.0
        assert outcome.detail["sim"] < SIM_LOOSE

    def test_a_day_apart_does_not_correspond(self):
        # 86400 is a whole multiple of 3600, so this also pins down that the
        # hour-artefact level does not swallow a next-day transaction.
        outcome = compare_timestamp(claim_at(86_400), TXN_AT, PARAMS)
        assert outcome.level_code == "TS_ELSE"
        assert outcome.detail["hour_offset"] is None

    def test_boundaries_are_inclusive(self):
        # The `>=` convention: a value exactly on a cut-point takes the better
        # level. Solve gauss(d) == SIM_CLOSE for d and land on it.
        ctx = dict(timestamp_ctx(claim_at(600), TXN_AT, PARAMS))
        ctx["sim"] = SIM_CLOSE
        assert TIMESTAMP.evaluate(None, None, ctx).level_code == "TS_CLOSE"
        ctx["sim"] = SIM_TIGHT
        assert TIMESTAMP.evaluate(None, None, ctx).level_code == "TS_TIGHT"
        ctx["sim"] = SIM_LOOSE
        assert TIMESTAMP.evaluate(None, None, ctx).level_code == "TS_LOOSE"


class TestWholeHourArtifact:
    @pytest.mark.parametrize(("seconds", "hours"), [(3600, 1), (-3600, -1), (5 * 3600, 5)])
    def test_a_whole_hour_out_is_its_own_level(self, seconds, hours):
        outcome = compare_timestamp(claim_at(seconds), TXN_AT, PARAMS)
        assert outcome.level_code == "TS_HOUR_ART"
        assert outcome.score == 0.25
        assert outcome.detail["hour_offset"] == hours

    def test_within_the_artifact_tolerance_still_counts(self):
        assert level_for(3600 + 90) == "TS_HOUR_ART"

    def test_outside_the_artifact_tolerance_does_not(self):
        assert level_for(3600 + 300) == "TS_ELSE"

    def test_beyond_the_range_of_real_offsets_it_is_not_an_artifact(self):
        # 20h is a whole number of hours but no timezone is 20h out.
        assert MAX_HOUR_ARTIFACT == 14
        outcome = compare_timestamp(claim_at(20 * 3600), TXN_AT, PARAMS)
        assert outcome.detail["hour_offset"] is None
        assert outcome.level_code == "TS_ELSE"

    def test_an_imprecise_reading_has_no_clock_to_be_an_hour_out_by(self):
        day = ClaimedInstant.from_local(
            datetime(2026, 3, 4, 0, 0), granularity_s=GRANULARITY_DAY
        )
        outcome = compare_timestamp(day, datetime(2026, 3, 4, 10, 0, tzinfo=PKT), PARAMS)
        assert outcome.detail["hour_offset"] is None


class TestImpreciseReadings:
    def test_date_inferred_never_reaches_a_precise_level(self):
        # Same instant, but the date was borrowed from the upload: the ladder
        # must not report "same time", however well the numbers line up.
        outcome = compare_timestamp(
            claim_at(0, granularity_s=GRANULARITY_MINUTE, date_inferred=True),
            TXN_AT,
            PARAMS,
        )
        assert outcome.level_code == "TS_DATE_ONLY"
        assert outcome.score == 0.60
        assert outcome.detail["sim"] == 1.0
        assert outcome.detail["precise"] is False

    def test_date_inferred_uses_the_wider_parameters(self):
        precise = compare_timestamp(claim_at(3 * 3600), TXN_AT, PARAMS)
        inferred = compare_timestamp(
            claim_at(3 * 3600, granularity_s=GRANULARITY_MINUTE, date_inferred=True),
            TXN_AT,
            PARAMS,
        )
        assert precise.level_code == "TS_HOUR_ART"
        assert inferred.level_code == "TS_DATE_ONLY"
        assert inferred.detail["offset_s"] == PARAMS.offset_s_date_inferred
        assert inferred.detail["scale_s"] == PARAMS.scale_s_date_inferred
        assert inferred.detail["sim"] > precise.detail["sim"]

    @pytest.mark.parametrize("hour", [0, 6, 13, 20, 23])
    def test_a_date_only_receipt_accepts_any_time_that_day(self, hour):
        day = ClaimedInstant.from_local(
            datetime(2026, 3, 4, 0, 0), granularity_s=GRANULARITY_DAY
        )
        txn = datetime(2026, 3, 4, hour, 17, tzinfo=PKT)
        outcome = compare_timestamp(day, txn, PARAMS)
        assert outcome.level_code == "TS_DATE_ONLY"
        assert outcome.detail["gap_s"] == 0.0
        assert outcome.detail["sim"] == 1.0

    def test_a_date_only_receipt_still_rejects_a_different_day(self):
        day = ClaimedInstant.from_local(
            datetime(2026, 3, 4, 0, 0), granularity_s=GRANULARITY_DAY
        )
        txn = datetime(2026, 3, 6, 12, 0, tzinfo=PKT)
        assert compare_timestamp(day, txn, PARAMS).level_code == "TS_ELSE"

    def test_window_gap_is_zero_inside_the_reading_and_grows_outside(self):
        day = ClaimedInstant.from_local(
            datetime(2026, 3, 4, 0, 0), granularity_s=GRANULARITY_DAY
        )
        assert window_gap_s(day, datetime(2026, 3, 4, 23, 59, tzinfo=PKT)) == 0.0
        assert window_gap_s(day, datetime(2026, 3, 5, 2, 0, tzinfo=PKT)) == 7200.0
        assert window_gap_s(day, datetime(2026, 3, 3, 22, 0, tzinfo=PKT)) == 7200.0


class TestMissing:
    def test_no_claimed_time(self):
        outcome = compare_timestamp(None, TXN_AT, PARAMS)
        assert outcome.level_code == "TS_MISSING"
        assert outcome.is_missing
        assert outcome.score == 0.0
        assert outcome.detail["sim"] == 0.0

    def test_no_transaction_time(self):
        outcome = compare_timestamp(claim_at(0), None, PARAMS)
        assert outcome.level_code == "TS_MISSING"
        assert outcome.detail["delta_s"] is None

    def test_missing_is_distinguishable_from_disagreement(self):
        # Both score 0.0; only one of them means "we could not look".
        assert compare_timestamp(claim_at(1800), TXN_AT, PARAMS).is_missing is False


class TestMonotonicDecay:
    # Deliberately avoids whole-hour distances: TS_HOUR_ART is a *different kind*
    # of evidence (an explainable systematic offset), not a rung of the decay
    # ladder, and it is allowed to outscore a nearer but unexplained gap.
    DISTANCES = (0, 30, 60, 120, 180, 240, 300, 450, 600, 900, 1020, 1500, 2400, 3000, 5000)

    def test_similarity_never_rises_with_distance(self):
        sims = [
            compare_timestamp(claim_at(d), TXN_AT, PARAMS).detail["sim"]
            for d in self.DISTANCES
        ]
        assert sims == sorted(sims, reverse=True)

    def test_level_score_never_rises_with_distance(self):
        scores = [
            compare_timestamp(claim_at(d), TXN_AT, PARAMS).score for d in self.DISTANCES
        ]
        assert scores == sorted(scores, reverse=True)

    def test_direction_of_the_error_does_not_change_the_score(self):
        """A receipt one minute early and one minute late are equally plausible.

        Not bit-identical, though: a reading pins down the half-open interval
        [t, t+granularity), so an early and a late transaction sit one
        granularity apart in gap terms. One second of a 900 s scale is well
        under any level boundary, which is exactly what this asserts.
        """
        for d in self.DISTANCES:
            early = compare_timestamp(claim_at(-d), TXN_AT, PARAMS)
            late = compare_timestamp(claim_at(d), TXN_AT, PARAMS)
            assert early.level_code == late.level_code
            assert early.detail["sim"] == pytest.approx(late.detail["sim"], abs=5e-3)


class TestParams:
    def test_from_policy_reads_the_versioned_thresholds(self):
        class StubPolicy:
            ts_offset_s = 120.0
            ts_scale_s = 900.0
            ts_offset_s_date_inferred = 21_600.0
            ts_scale_s_date_inferred = 43_200.0
            hour_artifact_tol_s = 90.0
            ts_sim_tight_t = 0.98
            ts_sim_close_t = 0.80
            ts_sim_loose_t = 0.40

        assert TimestampParams.from_policy(StubPolicy()) == PARAMS
        assert TimestampParams.from_policy(DecisionPolicy()) == PARAMS

    @pytest.mark.parametrize(
        "override",
        [
            {"offset_s": -1.0},
            {"scale_s": 0.0},
            {"scale_s_date_inferred": -1.0},
            {"hour_artifact_tol_s": -1.0},
            {"sim_tight": 1.5},
            {"sim_close": -0.1},
            # Cut-points that cross would make a rung unreachable and the
            # explanation a lie.
            {"sim_close": 0.99},
        ],
    )
    def test_impossible_parameters_are_rejected(self, override):
        base = {
            "offset_s": 120.0,
            "scale_s": 900.0,
            "offset_s_date_inferred": 21_600.0,
            "scale_s_date_inferred": 43_200.0,
            "hour_artifact_tol_s": 90.0,
            "sim_tight": 0.98,
            "sim_close": 0.80,
            "sim_loose": 0.40,
        }
        with pytest.raises(ValueError):
            TimestampParams(**{**base, **override})

    def test_the_pair_in_force_is_recorded_in_the_evidence(self):
        outcome = compare_timestamp(claim_at(0), TXN_AT, PARAMS)
        assert outcome.detail["offset_s"] == PARAMS.offset_s
        assert outcome.detail["scale_s"] == PARAMS.scale_s

    def test_the_cut_points_in_force_are_recorded_in_the_evidence(self):
        """The level fired against a number; the drawer has to show which one.

        Asserted on both branches of `timestamp_ctx`, because the unreadable
        case builds its metric bundle separately and a level predicate that
        found no `t_sim_*` key there would raise inside a decision.
        """
        for outcome in (
            compare_timestamp(claim_at(0), TXN_AT, PARAMS),
            compare_timestamp(None, TXN_AT, PARAMS),
        ):
            assert outcome.detail["t_sim_tight"] == PARAMS.sim_tight
            assert outcome.detail["t_sim_close"] == PARAMS.sim_close
            assert outcome.detail["t_sim_loose"] == PARAMS.sim_loose

    def test_a_retuned_cut_point_moves_the_level_it_carves(self):
        """The defect this move exists to prevent, in one assertion.

        Raising `sim_close` used to change a verdict while the policy
        fingerprint, ruleset version and engine version all stayed identical -
        so a stored decision was not reconstructable from its stamps. The
        cut-point is policy now: the level still moves, and the fingerprint
        moves with it.
        """
        from dataclasses import replace

        strict = replace(PARAMS, sim_close=0.95)
        # Ten minutes out: sim ~0.87, comfortably inside TS_CLOSE at 0.80 and
        # outside it at 0.95.
        assert compare_timestamp(claim_at(600), TXN_AT, PARAMS).level_code == "TS_CLOSE"
        assert compare_timestamp(claim_at(600), TXN_AT, strict).level_code == "TS_LOOSE"

        base = DecisionPolicy()
        assert replace(base, ts_sim_close_t=0.95).fingerprint() != base.fingerprint()


class TestObservations:
    def test_an_assumed_timezone_is_recorded(self):
        outcome = compare_timestamp(claim_at(0), TXN_AT, PARAMS)
        assert timestamp_observations(outcome) == (ObservationCode.TIME_TZ_ASSUMED,)

    def test_a_stated_timezone_produces_no_note(self):
        outcome = compare_timestamp(claim_at(0, tz_stated=True), TXN_AT, PARAMS)
        assert timestamp_observations(outcome) == ()

    def test_inferred_date_and_hour_offset_are_both_reported(self):
        outcome = compare_timestamp(claim_at(3600, tz_stated=True), TXN_AT, PARAMS)
        assert timestamp_observations(outcome) == (
            ObservationCode.TIME_WHOLE_HOUR_OFFSET,
        )
        inferred = compare_timestamp(
            claim_at(0, granularity_s=GRANULARITY_MINUTE, date_inferred=True, tz_stated=True),
            TXN_AT,
            PARAMS,
        )
        assert timestamp_observations(inferred) == (ObservationCode.TIME_DATE_INFERRED,)

    def test_a_missing_time_assumes_nothing(self):
        assert timestamp_observations(compare_timestamp(None, TXN_AT, PARAMS)) == ()
