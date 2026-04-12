"""Test day-count calculations — pure functions, no mocks needed."""

from datetime import date

import pytest

from fi_claude.curves.day_count import year_fraction
from fi_claude.data.common import DayCountConvention


def test_act_360():
    yf = year_fraction(date(2025, 1, 1), date(2025, 7, 1), DayCountConvention.ACT_360)
    assert abs(yf - 181 / 360) < 1e-10


def test_act_365():
    yf = year_fraction(date(2025, 1, 1), date(2025, 7, 1), DayCountConvention.ACT_365)
    assert abs(yf - 181 / 365) < 1e-10


def test_thirty_360():
    yf = year_fraction(date(2025, 1, 15), date(2025, 7, 15), DayCountConvention.THIRTY_360)
    assert abs(yf - 0.5) < 1e-10


def test_bus_252_requires_business_days():
    with pytest.raises(ValueError, match="business_days"):
        year_fraction(date(2025, 1, 1), date(2025, 7, 1), DayCountConvention.BUS_252)


def test_bus_252_with_business_days():
    yf = year_fraction(
        date(2025, 1, 1), date(2025, 7, 1), DayCountConvention.BUS_252, business_days=126
    )
    assert abs(yf - 126 / 252) < 1e-10


def test_same_date_returns_zero():
    yf = year_fraction(date(2025, 1, 1), date(2025, 1, 1), DayCountConvention.ACT_360)
    assert yf == 0.0


def test_reversed_dates_returns_zero():
    yf = year_fraction(date(2025, 7, 1), date(2025, 1, 1), DayCountConvention.ACT_360)
    assert yf == 0.0
