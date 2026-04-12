"""Tests for curve bootstrap — rate-to-DF conversion."""

from datetime import date

import pytest

from fi_claude.curves.bootstrap import (
    build_brl_cdi_curve,
    build_yield_curve,
    discount_factor_from_di_rate,
    discount_factor_from_yield,
    _tenor_to_days,
)
from fi_claude.data.common import Currency


# ---------------------------------------------------------------------------
# discount_factor_from_di_rate
# ---------------------------------------------------------------------------


class TestDiRateToDF:
    """BRL DI convention: df = 1 / (1 + r)^(bd/252)."""

    def test_zero_business_days(self):
        assert discount_factor_from_di_rate(0.14, 0) == 1.0

    def test_one_year_at_14pct(self):
        # 252 business days, rate = 14% → df = 1/(1.14)^1
        df = discount_factor_from_di_rate(0.14, 252)
        assert df == pytest.approx(1.0 / 1.14, rel=1e-10)

    def test_half_year_at_14pct(self):
        # 126 business days → df = 1/(1.14)^0.5
        df = discount_factor_from_di_rate(0.14, 126)
        expected = 1.0 / (1.14 ** 0.5)
        assert df == pytest.approx(expected, rel=1e-10)

    def test_two_years_at_13_57pct(self):
        # Real market rate: 2Y at 13.57%, ~504 BD
        df = discount_factor_from_di_rate(0.1357, 504)
        expected = 1.0 / (1.1357 ** 2.0)
        assert df == pytest.approx(expected, rel=1e-10)

    def test_higher_rate_lower_df(self):
        df_low = discount_factor_from_di_rate(0.10, 252)
        df_high = discount_factor_from_di_rate(0.15, 252)
        assert df_high < df_low

    def test_longer_tenor_lower_df(self):
        df_short = discount_factor_from_di_rate(0.14, 126)
        df_long = discount_factor_from_di_rate(0.14, 504)
        assert df_long < df_short


# ---------------------------------------------------------------------------
# discount_factor_from_yield
# ---------------------------------------------------------------------------


class TestYieldToDF:
    """USD/EUR convention: semi-annual, annual, or continuous."""

    def test_semi_annual_2y(self):
        # df = 1 / (1 + r/2)^(2*2) = 1/(1.019)^4
        df = discount_factor_from_yield(0.038, 2.0, "semi-annual")
        expected = 1.0 / (1.019 ** 4)
        assert df == pytest.approx(expected, rel=1e-10)

    def test_annual_1y(self):
        df = discount_factor_from_yield(0.05, 1.0, "annual")
        assert df == pytest.approx(1.0 / 1.05, rel=1e-10)

    def test_continuous(self):
        import math
        df = discount_factor_from_yield(0.04, 5.0, "continuous")
        expected = math.exp(-0.04 * 5.0)
        assert df == pytest.approx(expected, rel=1e-10)

    def test_zero_years(self):
        assert discount_factor_from_yield(0.05, 0.0) == 1.0

    def test_unknown_compounding(self):
        with pytest.raises(ValueError, match="Unknown compounding"):
            discount_factor_from_yield(0.05, 1.0, "quarterly")


# ---------------------------------------------------------------------------
# _tenor_to_days
# ---------------------------------------------------------------------------


class TestTenorParsing:
    def test_months(self):
        assert _tenor_to_days("3M") == round(3 * 30.4375)
        assert _tenor_to_days("6M") == round(6 * 30.4375)

    def test_years(self):
        assert _tenor_to_days("1Y") == round(365.25)
        assert _tenor_to_days("10Y") == round(10 * 365.25)

    def test_weeks(self):
        assert _tenor_to_days("2W") == 14

    def test_days(self):
        assert _tenor_to_days("30D") == 30

    def test_case_insensitive(self):
        assert _tenor_to_days("3m") == _tenor_to_days("3M")

    def test_invalid(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            _tenor_to_days("3X")


# ---------------------------------------------------------------------------
# build_brl_cdi_curve
# ---------------------------------------------------------------------------


class TestBuildBrlCdiCurve:
    def test_returns_discount_curve(self):
        curve = build_brl_cdi_curve(
            date(2026, 4, 10),
            {"1Y": 0.14, "2Y": 0.135},
        )
        assert curve.currency == Currency.BRL
        assert len(curve.nodes) == 3  # T=0 + 2 tenors

    def test_t0_node_is_one(self):
        curve = build_brl_cdi_curve(
            date(2026, 4, 10),
            {"1Y": 0.14},
        )
        assert curve.nodes[0].value == 1.0
        assert curve.nodes[0].date == date(2026, 4, 10)

    def test_nodes_sorted_by_date(self):
        curve = build_brl_cdi_curve(
            date(2026, 4, 10),
            {"2Y": 0.135, "6M": 0.14, "1Y": 0.137},
        )
        dates = [n.date for n in curve.nodes]
        assert dates == sorted(dates)

    def test_discount_factors_decrease(self):
        curve = build_brl_cdi_curve(
            date(2026, 4, 10),
            {"3M": 0.14, "1Y": 0.137, "5Y": 0.135},
        )
        dfs = [n.value for n in curve.nodes]
        # DFs should decrease with maturity (including T=0 = 1.0)
        for i in range(len(dfs) - 1):
            assert dfs[i] > dfs[i + 1]

    def test_implied_rates_roundtrip(self):
        """Implied rates from the curve should match input rates."""
        ref = date(2026, 4, 10)
        rates = {"1Y": 0.14}
        curve = build_brl_cdi_curve(ref, rates)

        # Skip T=0 node, check the 1Y node
        node = curve.nodes[1]
        cal_days = (node.date - ref).days
        bd = round(cal_days * 252 / 365.25)
        implied = (1.0 / node.value) ** (252.0 / bd) - 1.0
        assert implied == pytest.approx(0.14, rel=1e-4)


# ---------------------------------------------------------------------------
# build_yield_curve
# ---------------------------------------------------------------------------


class TestBuildYieldCurve:
    def test_usd_curve(self):
        curve = build_yield_curve(
            date(2026, 4, 10),
            Currency.USD,
            {"1Y": 0.037, "5Y": 0.04, "10Y": 0.043},
        )
        assert curve.currency == Currency.USD
        assert len(curve.nodes) == 4  # T=0 + 3 tenors

    def test_nodes_sorted(self):
        curve = build_yield_curve(
            date(2026, 4, 10),
            Currency.EUR,
            {"10Y": 0.03, "1Y": 0.025, "5Y": 0.028},
        )
        dates = [n.date for n in curve.nodes]
        assert dates == sorted(dates)
