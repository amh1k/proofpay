"""Money is an integer count of paisa, and the boundaries are the whole point."""

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from proofpay.core import money as money_module
from proofpay.core.money import Money


class TestConstruction:
    def test_minor_units_are_exact_ints(self):
        assert Money(150_000).minor == 150_000
        assert Money(150_000).currency == "PKR"

    def test_float_minor_is_rejected(self):
        with pytest.raises(TypeError):
            Money(1500.0)

    def test_bool_minor_is_rejected(self):
        # bool is an int subclass; Money(True) would silently mean 1 paisa.
        with pytest.raises(TypeError):
            Money(True)

    def test_decimal_minor_is_rejected(self):
        with pytest.raises(TypeError):
            Money(Decimal("1500"))

    def test_unknown_currency_is_rejected(self):
        with pytest.raises(ValueError):
            Money(100, "USD")

    def test_zero_helper(self):
        assert Money.zero() == Money(0, "PKR")

    def test_is_hashable_and_frozen(self):
        m = Money(100)
        assert {m, Money(100)} == {Money(100)}
        with pytest.raises(FrozenInstanceError):
            m.minor = 5  # type: ignore[misc]


class TestFromMajor:
    @pytest.mark.parametrize(
        "major,expected_minor",
        [
            ("1500", 150_000),
            ("1500.00", 150_000),
            ("1500.5", 150_050),
            ("0.01", 1),
            ("0", 0),
            (1500, 150_000),
            (Decimal("1500.99"), 150_099),
            ("-25.50", -2_550),
        ],
    )
    def test_major_to_minor(self, major, expected_minor):
        assert Money.from_major(major).minor == expected_minor

    @pytest.mark.parametrize(
        "major,expected_minor",
        [
            ("1.005", 101),   # half-up, not banker's rounding
            ("1.004", 100),
            ("2.345", 235),
            ("-1.005", -101),
        ],
    )
    def test_rounding_is_half_up(self, major, expected_minor):
        assert Money.from_major(major).minor == expected_minor

    def test_float_is_refused_outright(self):
        # By the time a float exists the precision is already gone.
        with pytest.raises(TypeError):
            Money.from_major(1500.0)

    def test_garbage_raises_value_error(self):
        with pytest.raises(ValueError):
            Money.from_major("not-an-amount")

    def test_infinity_is_refused(self):
        with pytest.raises(ValueError):
            Money.from_major("Infinity")


class TestArithmetic:
    def test_add(self):
        assert Money(100) + Money(250) == Money(350)

    def test_sub(self):
        assert Money(100) - Money(250) == Money(-150)

    def test_sub_keeps_the_sign(self):
        # The sign is the fraud signal; abs() would delete it.
        assert (Money(500) - Money(900)).minor < 0

    def test_neg_and_abs(self):
        assert -Money(150) == Money(-150)
        assert abs(Money(-150)) == Money(150)

    def test_adding_a_non_money_raises(self):
        with pytest.raises(TypeError):
            Money(100) + 100  # type: ignore[operator]

    def test_currency_mismatch_raises(self, monkeypatch):
        # Only PKR is registered today, so a second currency has to be injected
        # to exercise the guard that will matter the day one is added.
        monkeypatch.setitem(money_module.MINOR_EXPONENT, "USD", 2)
        with pytest.raises(ValueError, match="currency mismatch"):
            Money(100, "PKR") + Money(100, "USD")
        with pytest.raises(ValueError, match="currency mismatch"):
            Money(100, "PKR") - Money(100, "USD")

    def test_ordering(self):
        assert Money(100) < Money(200)
        assert max(Money(100), Money(900), Money(300)) == Money(900)

    def test_equality_is_exact_at_the_boundary(self):
        # The float trap this class exists to avoid: 0.1 + 0.2 != 0.3.
        tenth = Money.from_major("0.10")
        fifth = Money.from_major("0.20")
        assert tenth + fifth == Money.from_major("0.30")


class TestDisplay:
    @pytest.mark.parametrize(
        "minor,text",
        [(150_000, "1500.00"), (1, "0.01"), (0, "0.00"), (-2_550, "-25.50")],
    )
    def test_as_major_str(self, minor, text):
        assert Money(minor).as_major_str == text

    def test_str_includes_currency(self):
        assert str(Money(150_000)) == "PKR 1500.00"

    def test_round_trips_through_from_major(self):
        m = Money(123_456)
        assert Money.from_major(m.as_major_str) == m
