"""Test seasoning statistics — theta, carry, rolldown, risk evolution."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from fi_claude.data.common import Cashflow, Currency, DayCountConvention, PayReceive
from fi_claude.data.curves import CurveNode, DiscountCurve, InflationCurve, InterpolationMethod
from fi_claude.data.instruments import (
    AgencyProgram,
    BrlPreCdiSwap,
    CouponScheduleEntry,
    InflationLinkedBond,
    TbaContract,
)
from fi_claude.data.market import MarketData
from fi_claude.pricers.brl_pre_cdi import price_brl_pre_cdi_swap
from fi_claude.pricers.inflation_bond import price_inflation_linked_bond
from fi_claude.pricers.tba import price_tba
from fi_claude.risk.seasoning import (
    HorizonResult,
    compute_seasoning,
    roll_market_forward,
    season_portfolio,
    _compute_carry,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def val_date() -> date:
    return date(2025, 6, 15)


@pytest.fixture
def usd_curve(val_date: date) -> DiscountCurve:
    return DiscountCurve(
        reference_date=val_date,
        currency=Currency.USD,
        nodes=(
            CurveNode(date=date(2025, 7, 15), value=0.9960),
            CurveNode(date=date(2025, 9, 15), value=0.9880),
            CurveNode(date=date(2025, 12, 15), value=0.9780),
            CurveNode(date=date(2026, 6, 15), value=0.9550),
            CurveNode(date=date(2027, 6, 15), value=0.9100),
            CurveNode(date=date(2030, 6, 15), value=0.7800),
            CurveNode(date=date(2035, 6, 15), value=0.6000),
            CurveNode(date=date(2055, 6, 15), value=0.2500),
        ),
        interpolation=InterpolationMethod.LOG_LINEAR,
    )


@pytest.fixture
def brl_curve(val_date: date) -> DiscountCurve:
    return DiscountCurve(
        reference_date=val_date,
        currency=Currency.BRL,
        nodes=(
            CurveNode(date=date(2025, 7, 15), value=0.9890),
            CurveNode(date=date(2025, 12, 15), value=0.9400),
            CurveNode(date=date(2026, 6, 15), value=0.8800),
            CurveNode(date=date(2027, 6, 15), value=0.7700),
        ),
        interpolation=InterpolationMethod.LOG_LINEAR,
    )


@pytest.fixture
def cpi_curve(val_date: date) -> InflationCurve:
    return InflationCurve(
        reference_date=val_date,
        base_index_level=310.0,
        nodes=(
            CurveNode(date=date(2025, 7, 15), value=311.5),
            CurveNode(date=date(2025, 12, 15), value=314.0),
            CurveNode(date=date(2026, 6, 15), value=317.0),
            CurveNode(date=date(2027, 6, 15), value=323.0),
        ),
    )


@pytest.fixture
def market(val_date: date, usd_curve: DiscountCurve, brl_curve: DiscountCurve,
           cpi_curve: InflationCurve) -> MarketData:
    return MarketData(
        valuation_date=val_date,
        discount_curves={
            "USD": usd_curve,
            "BRL-CDI": brl_curve,
            "USD-REAL": usd_curve,
        },
        inflation_curves={"US-CPI": cpi_curve},
    )


@pytest.fixture
def tba() -> TbaContract:
    return TbaContract(
        agency=AgencyProgram.FNMA,
        coupon_rate=0.055,
        original_term_years=30,
        face_value=Decimal("1000000"),
        settlement_date=date(2025, 7, 15),
        assumed_cpr=0.08,
    )


@pytest.fixture
def brl_swap() -> BrlPreCdiSwap:
    return BrlPreCdiSwap(
        notional=Decimal("10000000"),
        fixed_rate=0.1350,
        start_date=date(2025, 6, 15),
        end_date=date(2026, 6, 15),
        pay_receive_fixed=PayReceive.PAY,
    )


@pytest.fixture
def tips_bond() -> InflationLinkedBond:
    return InflationLinkedBond(
        face_value=Decimal("1000000"),
        real_coupon_rate=0.0125,
        issue_date=date(2024, 1, 15),
        maturity_date=date(2027, 1, 15),
        currency=Currency.USD,
        day_count=DayCountConvention.ACT_ACT,
        base_cpi=305.0,
        coupon_schedule=(
            CouponScheduleEntry(
                accrual_start=date(2025, 7, 15),
                accrual_end=date(2026, 1, 15),
                payment_date=date(2026, 1, 15),
            ),
            CouponScheduleEntry(
                accrual_start=date(2026, 1, 15),
                accrual_end=date(2026, 7, 15),
                payment_date=date(2026, 7, 15),
            ),
            CouponScheduleEntry(
                accrual_start=date(2026, 7, 15),
                accrual_end=date(2027, 1, 15),
                payment_date=date(2027, 1, 15),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# roll_market_forward
# ---------------------------------------------------------------------------


class TestRollMarketForward:
    def test_valuation_date_advances(self, market: MarketData):
        rolled = roll_market_forward(market, 7)
        assert rolled.valuation_date == date(2025, 6, 22)

    def test_curve_nodes_shift(self, market: MarketData):
        rolled = roll_market_forward(market, 7)
        orig_dates = [n.date for n in market.discount_curves["USD"].nodes]
        rolled_dates = [n.date for n in rolled.discount_curves["USD"].nodes]
        for o, r in zip(orig_dates, rolled_dates):
            assert r == o + timedelta(days=7)

    def test_discount_factors_preserved(self, market: MarketData):
        rolled = roll_market_forward(market, 7)
        orig_values = [n.value for n in market.discount_curves["USD"].nodes]
        rolled_values = [n.value for n in rolled.discount_curves["USD"].nodes]
        assert orig_values == rolled_values

    def test_reference_date_shifts(self, market: MarketData):
        rolled = roll_market_forward(market, 7)
        assert rolled.discount_curves["USD"].reference_date == date(2025, 6, 22)

    def test_inflation_curve_shifts(self, market: MarketData):
        rolled = roll_market_forward(market, 7)
        orig_dates = [n.date for n in market.inflation_curves["US-CPI"].nodes]
        rolled_dates = [n.date for n in rolled.inflation_curves["US-CPI"].nodes]
        for o, r in zip(orig_dates, rolled_dates):
            assert r == o + timedelta(days=7)

    def test_original_unchanged(self, market: MarketData):
        orig_date = market.valuation_date
        _ = roll_market_forward(market, 7)
        assert market.valuation_date == orig_date


# ---------------------------------------------------------------------------
# Carry computation
# ---------------------------------------------------------------------------


class TestCarry:
    def test_carry_includes_window(self):
        cfs = (
            Cashflow(payment_date=date(2025, 6, 15), amount=Decimal("100"), currency=Currency.USD),
            Cashflow(payment_date=date(2025, 6, 16), amount=Decimal("200"), currency=Currency.USD),
            Cashflow(payment_date=date(2025, 6, 20), amount=Decimal("300"), currency=Currency.USD),
            Cashflow(payment_date=date(2025, 6, 25), amount=Decimal("400"), currency=Currency.USD),
        )
        # Window (6/15, 6/22] should include 6/16 and 6/20 but not 6/15 or 6/25
        carry = _compute_carry(cfs, date(2025, 6, 15), date(2025, 6, 22))
        assert carry == 500.0

    def test_carry_empty_window(self):
        cfs = (
            Cashflow(payment_date=date(2025, 7, 15), amount=Decimal("1000"), currency=Currency.USD),
        )
        carry = _compute_carry(cfs, date(2025, 6, 15), date(2025, 6, 22))
        assert carry == 0.0

    def test_carry_boundary_end_inclusive(self):
        cfs = (
            Cashflow(payment_date=date(2025, 6, 22), amount=Decimal("500"), currency=Currency.USD),
        )
        carry = _compute_carry(cfs, date(2025, 6, 15), date(2025, 6, 22))
        assert carry == 500.0

    def test_carry_boundary_start_exclusive(self):
        cfs = (
            Cashflow(payment_date=date(2025, 6, 15), amount=Decimal("500"), currency=Currency.USD),
        )
        carry = _compute_carry(cfs, date(2025, 6, 15), date(2025, 6, 22))
        assert carry == 0.0


# ---------------------------------------------------------------------------
# TBA seasoning
# ---------------------------------------------------------------------------


class TestTbaSeasoning:
    def _pricer(self, tba: TbaContract):
        return lambda m: price_tba(tba, m)

    def test_1d_theta_nonzero(self, tba: TbaContract, market: MarketData):
        """Rolling curves forward changes where cashflows land on the curve."""
        result = compute_seasoning(self._pricer(tba), market, horizon_days=1,
                                   rate_curve_keys=("USD",))
        assert result.total_theta != 0.0
        assert result.horizon_label == "1D"

    def test_theta_decomposes(self, tba: TbaContract, market: MarketData):
        """total_theta = carry + rolldown, always."""
        result = compute_seasoning(self._pricer(tba), market, horizon_days=7)
        assert abs(result.total_theta - result.carry - result.rolldown) < 0.01

    def test_7d_theta_larger_than_1d(self, tba: TbaContract, market: MarketData):
        r1 = compute_seasoning(self._pricer(tba), market, horizon_days=1)
        r7 = compute_seasoning(self._pricer(tba), market, horizon_days=7)
        # 7-day theta should be larger in magnitude (more time passes)
        assert abs(r7.total_theta) > abs(r1.total_theta)

    def test_annualized_consistent(self, tba: TbaContract, market: MarketData):
        result = compute_seasoning(self._pricer(tba), market, horizon_days=7)
        expected = result.total_theta * 365.0 / 7
        assert abs(result.theta_annual - expected) < 0.01

    def test_rolldown_positive_upward_sloping_curve(self, tba: TbaContract, market: MarketData):
        """On an upward-sloping curve, a long bond rolls into higher DFs → positive rolldown."""
        result = compute_seasoning(self._pricer(tba), market, horizon_days=7)
        # TBA cashflows are far out; rolling the curve forward means each
        # cashflow now reads off a slightly shorter tenor (higher DF) → PV up
        assert result.rolldown > 0

    def test_dv01_present_and_negative(self, tba: TbaContract, market: MarketData):
        result = compute_seasoning(self._pricer(tba), market, horizon_days=1,
                                   rate_curve_keys=("USD",))
        assert "USD" in result.base_risk.dv01
        assert "USD" in result.horizon_risk.dv01
        assert result.base_risk.dv01["USD"] < 0  # long bond: rates up → PV down

    def test_dv01_change_direction(self, tba: TbaContract, market: MarketData):
        """DV01 magnitude should decrease slightly as the instrument ages."""
        result = compute_seasoning(self._pricer(tba), market, horizon_days=7,
                                   rate_curve_keys=("USD",))
        base_mag = abs(result.base_risk.dv01["USD"])
        horiz_mag = abs(result.horizon_risk.dv01["USD"])
        # Over 1 week, the change is small. Allow generous tolerance.
        assert horiz_mag <= base_mag + 5.0


# ---------------------------------------------------------------------------
# BRL swap seasoning
# ---------------------------------------------------------------------------


class TestBrlSwapSeasoning:
    def _pricer(self, swap: BrlPreCdiSwap):
        return lambda m: price_brl_pre_cdi_swap(swap, m, business_days=252)

    def test_theta_decomposes(self, brl_swap: BrlPreCdiSwap, market: MarketData):
        result = compute_seasoning(self._pricer(brl_swap), market, horizon_days=1)
        assert abs(result.total_theta - result.carry - result.rolldown) < 0.01

    def test_dv01_computed(self, brl_swap: BrlPreCdiSwap, market: MarketData):
        result = compute_seasoning(self._pricer(brl_swap), market, horizon_days=1,
                                   rate_curve_keys=("BRL-CDI",))
        assert "BRL-CDI" in result.base_risk.dv01

    def test_dv01_change_exists(self, brl_swap: BrlPreCdiSwap, market: MarketData):
        result = compute_seasoning(self._pricer(brl_swap), market, horizon_days=7,
                                   rate_curve_keys=("BRL-CDI",))
        assert "BRL-CDI" in result.dv01_change


# ---------------------------------------------------------------------------
# Inflation bond seasoning
# ---------------------------------------------------------------------------


class TestInflationBondSeasoning:
    def _pricer(self, bond: InflationLinkedBond):
        return lambda m: price_inflation_linked_bond(bond, m)

    def test_theta_decomposes(self, tips_bond: InflationLinkedBond, market: MarketData):
        result = compute_seasoning(self._pricer(tips_bond), market, horizon_days=7,
                                   rate_curve_keys=("USD-REAL",))
        assert abs(result.total_theta - result.carry - result.rolldown) < 0.01

    def test_carry_zero_no_coupon_in_window(self, tips_bond: InflationLinkedBond, market: MarketData):
        """Bond's next coupon is 2026-01-15 — no carry in a 7-day window from 2025-06-15."""
        result = compute_seasoning(self._pricer(tips_bond), market, horizon_days=7)
        assert result.carry == 0.0

    def test_rolldown_nonzero(self, tips_bond: InflationLinkedBond, market: MarketData):
        """Even without carry, rolldown should be nonzero on a normal curve."""
        result = compute_seasoning(self._pricer(tips_bond), market, horizon_days=7)
        assert result.rolldown != 0.0


# ---------------------------------------------------------------------------
# CS01 tests
# ---------------------------------------------------------------------------


class TestCs01:
    def test_cs01_with_credit_curve(self, tba: TbaContract, market: MarketData):
        """Designating USD as a credit curve produces CS01 identical to DV01."""
        pricer = lambda m: price_tba(tba, m)
        result = compute_seasoning(pricer, market, horizon_days=1,
                                   credit_curve_keys=("USD",))
        assert "USD" in result.base_risk.cs01

        # CS01 bumps the same curve the same way as DV01 → should match
        result_dv01 = compute_seasoning(pricer, market, horizon_days=1,
                                        rate_curve_keys=("USD",))
        assert abs(result.base_risk.cs01["USD"] - result_dv01.base_risk.dv01["USD"]) < 0.01

    def test_cs01_empty_when_no_credit_curves(self, tba: TbaContract, market: MarketData):
        pricer = lambda m: price_tba(tba, m)
        result = compute_seasoning(pricer, market, horizon_days=1)
        assert result.base_risk.cs01 == {}
        assert result.cs01_change == {}

    def test_cs01_change_over_horizon(self, tba: TbaContract, market: MarketData):
        pricer = lambda m: price_tba(tba, m)
        result = compute_seasoning(pricer, market, horizon_days=7,
                                   credit_curve_keys=("USD",))
        assert "USD" in result.cs01_change


# ---------------------------------------------------------------------------
# Multi-horizon (season_portfolio)
# ---------------------------------------------------------------------------


class TestSeasonPortfolio:
    def test_multiple_horizons(self, tba: TbaContract, market: MarketData):
        pricer = lambda m: price_tba(tba, m)
        report = season_portfolio(pricer, market,
                                  horizons=(1, 7),
                                  rate_curve_keys=("USD",))
        assert len(report.horizons) == 2
        assert report.horizons[0].horizon_label == "1D"
        assert report.horizons[1].horizon_label == "1W"

    def test_instrument_type_propagated(self, tba: TbaContract, market: MarketData):
        pricer = lambda m: price_tba(tba, m)
        report = season_portfolio(pricer, market, horizons=(1,))
        assert report.instrument_type == "TBA"
        assert report.currency == "USD"

    def test_decomposition_holds_all_horizons(self, tba: TbaContract, market: MarketData):
        pricer = lambda m: price_tba(tba, m)
        report = season_portfolio(pricer, market, horizons=(1, 7, 30))
        for h in report.horizons:
            assert abs(h.total_theta - h.carry - h.rolldown) < 0.01

    def test_custom_horizons(self, tba: TbaContract, market: MarketData):
        pricer = lambda m: price_tba(tba, m)
        report = season_portfolio(pricer, market, horizons=(3, 14, 90))
        assert report.horizons[0].horizon_label == "3D"
        assert report.horizons[1].horizon_label == "2W"
        assert report.horizons[2].horizon_label == "3M"

    def test_longer_horizon_larger_theta(self, tba: TbaContract, market: MarketData):
        pricer = lambda m: price_tba(tba, m)
        report = season_portfolio(pricer, market, horizons=(1, 7, 30))
        thetas = [abs(h.total_theta) for h in report.horizons]
        assert thetas[0] < thetas[1] < thetas[2]
