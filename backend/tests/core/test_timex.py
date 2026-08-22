"""Timezone-aware instants, and the honest record of what was assumed."""

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from proofpay.core.timex import (
    GRANULARITY_DAY,
    GRANULARITY_MINUTE,
    GRANULARITY_SECOND,
    PKT,
    UTC,
    ClaimedInstant,
    hour_offset_artifact,
    require_aware,
    seconds_between,
)

# Asia/Karachi is UTC+05:00 with no DST, so this pairing is exact all year.
PKT_NOON = datetime(2026, 3, 1, 12, 0, tzinfo=PKT)
UTC_0700 = datetime(2026, 3, 1, 7, 0, tzinfo=UTC)


class TestRequireAware:
    def test_naive_datetime_is_refused(self):
        with pytest.raises(ValueError, match="naive"):
            require_aware(datetime(2026, 3, 1, 12, 0))

    def test_utc_passes_through_unchanged(self):
        assert require_aware(UTC_0700) == UTC_0700

    def test_karachi_converts_to_utc(self):
        converted = require_aware(PKT_NOON)
        assert converted == UTC_0700
        assert converted.tzinfo is UTC
        assert converted.hour == 7

    def test_karachi_has_no_dst_transition(self):
        for month in (1, 4, 7, 10):
            local = datetime(2026, month, 1, 12, 0, tzinfo=PKT)
            assert local.utcoffset() == timedelta(hours=5)

    def test_a_fixed_offset_zone_is_accepted(self):
        plus_five = timezone(timedelta(hours=5))
        assert require_aware(datetime(2026, 3, 1, 12, 0, tzinfo=plus_five)) == UTC_0700


class TestSecondsBetween:
    def test_signed_difference(self):
        later = UTC_0700 + timedelta(seconds=90)
        assert seconds_between(later, UTC_0700) == 90.0
        assert seconds_between(UTC_0700, later) == -90.0

    def test_compares_across_zones(self):
        assert seconds_between(PKT_NOON, UTC_0700) == 0.0

    def test_naive_input_is_refused(self):
        with pytest.raises(ValueError):
            seconds_between(datetime(2026, 3, 1, 12, 0), UTC_0700)


class TestHourOffsetArtifact:
    @pytest.mark.parametrize(
        "delta_s,expected",
        [
            (3600.0, 1),        # exactly one hour out
            (-3600.0, -1),
            (3660.0, 1),        # an hour plus a minute, still within tolerance
            (18_000.0, 5),      # the PKT offset itself: a doctored or mis-zoned receipt
            (0.0, None),        # a perfect match is not an artefact
            (60.0, None),       # ordinary clock skew
            (3900.0, None),     # 65 minutes: too far off the hour to blame a zone
        ],
    )
    def test_detects_whole_hour_offsets(self, delta_s, expected):
        assert hour_offset_artifact(delta_s, 90.0) == expected

    def test_zero_is_never_an_artifact(self):
        # A zero multiple would flag every exact match as suspicious.
        assert hour_offset_artifact(1.0, 90.0) is None

    def test_negative_tolerance_is_rejected(self):
        with pytest.raises(ValueError):
            hour_offset_artifact(3600.0, -1.0)


class TestClaimedInstant:
    def test_naive_resolved_utc_is_refused(self):
        with pytest.raises(ValueError, match="naive"):
            ClaimedInstant(resolved_utc=datetime(2026, 3, 1, 12, 0))

    def test_local_time_is_normalised_to_utc(self):
        ci = ClaimedInstant(resolved_utc=PKT_NOON)
        assert ci.resolved_utc == UTC_0700
        assert ci.resolved_utc.tzinfo is UTC

    def test_defaults_are_the_conservative_ones(self):
        ci = ClaimedInstant(resolved_utc=UTC_0700)
        assert ci.granularity_s == GRANULARITY_SECOND
        assert ci.assumed_tz == "Asia/Karachi"
        assert ci.tz_stated is False
        assert ci.date_inferred is False

    def test_non_positive_granularity_is_refused(self):
        with pytest.raises(ValueError):
            ClaimedInstant(resolved_utc=UTC_0700, granularity_s=0)

    def test_from_local_attaches_the_assumed_zone(self):
        # "04:12 PM" on a receipt with no zone: the assumption is recorded.
        ci = ClaimedInstant.from_local(
            datetime(2026, 3, 1, 16, 12), granularity_s=GRANULARITY_MINUTE
        )
        assert ci.resolved_utc == datetime(2026, 3, 1, 11, 12, tzinfo=UTC)
        assert ci.assumed_tz == "Asia/Karachi"
        assert ci.tz_stated is False
        assert ci.granularity_s == GRANULARITY_MINUTE

    def test_from_local_keeps_a_stated_zone(self):
        ci = ClaimedInstant.from_local(PKT_NOON, tz_stated=True)
        assert ci.resolved_utc == UTC_0700
        assert ci.tz_stated is True

    def test_precision_distinguishes_a_read_time_from_an_inferred_date(self):
        precise = ClaimedInstant(resolved_utc=UTC_0700, granularity_s=GRANULARITY_SECOND)
        minute = ClaimedInstant(resolved_utc=UTC_0700, granularity_s=GRANULARITY_MINUTE)
        inferred = ClaimedInstant(
            resolved_utc=UTC_0700, granularity_s=GRANULARITY_DAY, date_inferred=True
        )
        assert precise.is_precise is True
        assert minute.is_precise is True
        assert inferred.is_precise is False

    def test_a_precise_reading_with_an_inferred_date_is_not_precise(self):
        # The clock was legible; the day was a guess. Tolerance must widen.
        ci = ClaimedInstant(
            resolved_utc=UTC_0700, granularity_s=GRANULARITY_SECOND, date_inferred=True
        )
        assert ci.is_precise is False

    @pytest.mark.parametrize(
        "granularity,uncertainty",
        [(GRANULARITY_SECOND, 0.5), (GRANULARITY_MINUTE, 30.0), (GRANULARITY_DAY, 43_200.0)],
    )
    def test_uncertainty_is_half_the_granularity(self, granularity, uncertainty):
        ci = ClaimedInstant(resolved_utc=UTC_0700, granularity_s=granularity)
        assert ci.uncertainty_s == uncertainty

    def test_window_spans_the_granularity(self):
        ci = ClaimedInstant(resolved_utc=UTC_0700, granularity_s=GRANULARITY_MINUTE)
        start, end = ci.window()
        assert start == UTC_0700
        assert end == UTC_0700 + timedelta(seconds=60)

    def test_is_frozen_and_hashable(self):
        ci = ClaimedInstant(resolved_utc=UTC_0700)
        assert {ci, ClaimedInstant(resolved_utc=UTC_0700)} == {ci}
        with pytest.raises(FrozenInstanceError):
            ci.date_inferred = True  # type: ignore[misc]
