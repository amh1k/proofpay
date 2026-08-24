"""Tests for proofpay.demo.clock — deterministic time anchor.

These tests verify that:
  - Default anchor returns the pinned constant (for test determinism)
  - at() correctly computes offsets from the anchor
  - to_utc() converts PKT → UTC correctly
  - to_utc() rejects naive (timezone-unaware) datetimes
  - PROOFPAY_DEMO_ANCHOR env var controls anchor in all three modes:
    unset (pinned), "today", and explicit ISO-8601
"""

from datetime import UTC, datetime

import pytest

from proofpay.demo.clock import PINNED_ANCHOR, PKT, anchor, at, to_utc


class TestAnchor:
    """anchor() must return the correct time based on environment config."""

    def test_default_is_pinned(self, monkeypatch):
        """With no env var set, anchor() returns the pinned constant."""
        monkeypatch.delenv("PROOFPAY_DEMO_ANCHOR", raising=False)
        assert anchor() == PINNED_ANCHOR

    def test_pinned_anchor_is_pkt(self):
        """The pinned anchor must be in Pakistan Standard Time."""
        assert PINNED_ANCHOR.tzinfo == PKT

    def test_pinned_anchor_date_and_time(self):
        """The pinned anchor must be 2026-08-20 at 14:05 PKT."""
        assert PINNED_ANCHOR.year == 2026
        assert PINNED_ANCHOR.month == 8
        assert PINNED_ANCHOR.day == 20
        assert PINNED_ANCHOR.hour == 14
        assert PINNED_ANCHOR.minute == 5

    def test_today_mode(self, monkeypatch):
        """'today' anchor should use today's date but keep 14:05 time."""
        monkeypatch.setenv("PROOFPAY_DEMO_ANCHOR", "today")
        result = anchor()
        today = datetime.now(PKT)
        assert result.year == today.year
        assert result.month == today.month
        assert result.day == today.day
        assert result.hour == 14
        assert result.minute == 5
        assert result.second == 0

    def test_iso_string_mode(self, monkeypatch):
        """An explicit ISO-8601 string should be parsed literally."""
        monkeypatch.setenv("PROOFPAY_DEMO_ANCHOR", "2026-08-22T10:00:00+05:00")
        result = anchor()
        assert result.hour == 10
        assert result.minute == 0

    def test_empty_string_treated_as_unset(self, monkeypatch):
        """An empty env var should behave the same as unset → pinned."""
        monkeypatch.setenv("PROOFPAY_DEMO_ANCHOR", "")
        assert anchor() == PINNED_ANCHOR

    def test_whitespace_only_treated_as_unset(self, monkeypatch):
        """Whitespace-only env var should behave the same as unset."""
        monkeypatch.setenv("PROOFPAY_DEMO_ANCHOR", "  ")
        assert anchor() == PINNED_ANCHOR


class TestAt:
    """at() must compute correct time offsets from the anchor."""

    def test_zero_offset_equals_anchor(self, monkeypatch):
        """at(0) must return exactly the anchor."""
        monkeypatch.delenv("PROOFPAY_DEMO_ANCHOR", raising=False)
        assert at(0) == PINNED_ANCHOR

    def test_negative_offset_is_before_anchor(self, monkeypatch):
        """at(-12) should be 12 minutes before the anchor."""
        monkeypatch.delenv("PROOFPAY_DEMO_ANCHOR", raising=False)
        result = at(-12)
        delta = (PINNED_ANCHOR - result).total_seconds()
        assert delta == 720  # 12 minutes = 720 seconds

    def test_positive_offset_is_after_anchor(self, monkeypatch):
        """at(5) should be 5 minutes after the anchor."""
        monkeypatch.delenv("PROOFPAY_DEMO_ANCHOR", raising=False)
        result = at(5)
        delta = (result - PINNED_ANCHOR).total_seconds()
        assert delta == 300  # 5 minutes = 300 seconds

    def test_large_negative_offset(self, monkeypatch):
        """at(-240) should be 4 hours before the anchor."""
        monkeypatch.delenv("PROOFPAY_DEMO_ANCHOR", raising=False)
        result = at(-240)
        assert result.hour == 10  # 14:05 minus 4 hours = 10:05
        assert result.minute == 5


class TestToUtc:
    """to_utc() must handle timezone conversion correctly."""

    def test_pkt_to_utc(self):
        """14:05 PKT should convert to 09:05 UTC (PKT = UTC+5)."""
        utc = to_utc(PINNED_ANCHOR)
        assert utc.hour == 9
        assert utc.minute == 5
        assert utc.tzinfo == UTC

    def test_rejects_naive_datetime(self):
        """A datetime without timezone info must raise ValueError."""
        with pytest.raises(ValueError, match="naive"):
            to_utc(datetime(2026, 1, 1, 12, 0, 0))

    def test_aware_datetime_converts(self):
        """Any aware datetime should convert without error."""
        aware = datetime(2026, 6, 15, 18, 30, 0, tzinfo=PKT)
        result = to_utc(aware)
        assert result.tzinfo == UTC
        assert result.hour == 13  # 18:30 PKT = 13:30 UTC
        assert result.minute == 30
