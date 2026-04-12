"""Test MXN TIIE swap pricer."""

from datetime import date
from decimal import Decimal

import pytest

from fi_claude.data.common import Currency, DayCountConvention, PayReceive
from fi_claude.data.curves import CurveNode, DiscountCurve, InterpolationMethod
from fi_claude.data.instruments import MxnTiieSwap
from fi_claude.data.market import MarketData
from fi_claude.data.results import PricingResult
from fi_claude.pricers.mxn_tiie import price_mxn_tiie_swap


# ---------------------------------------------------------------------------
# Fixtures — steep EM curve: ~11% short rates declining to ~9% long end
# ---------------------------------------------------------------------------


@pytest.fixture
def valuation_date() -> date:
    return date(2025, 6, 15)


@pytest.fixture
def mxn_tiie_curve(valuation_date: date) -> DiscountCurve:
    """MXN TIIE discount curve — steep EM curve.

    Short end ~11%, long end ~9%. Discount factors derived from
    continuous compounding: df = exp(-r * t).
    Approximate nodes:
      1M:  df ~ 0.9909  (r ~ 11.0%)
      3M:  df ~ 0.9735  (r ~ 10.8%)
      6M:  df ~ 0.9477  (r ~ 10.5%)
      1Y:  df ~ 0.9000  (r ~ 10.0%)
      2Y:  df ~ 0.8187  (r ~  9.5%)
    """
    return DiscountCurve(
        reference_date=valuation_date,
        currency=Currency.MXN,
        nodes=(
            CurveNode(date=date(2025, 7, 15), value=0.9909),
            CurveNode(date=date(2025, 9, 15), value=0.9735),
            CurveNode(date=date(2025, 12, 15), value=0.9477),
            CurveNode(date=date(2026, 6, 15), value=0.9000),
            CurveNode(date=date(2027, 6, 15), value=0.8187),
        ),
        interpolation=InterpolationMethod.LOG_LINEAR,
    )


@pytest.fixture
def mxn_market(valuation_date: date, mxn_tiie_curve: DiscountCurve) -> MarketData:
    return MarketData(
        valuation_date=valuation_date,
        discount_curves={"MXN-TIIE": mxn_tiie_curve},
    )


@pytest.fixture
def sample_mxn_swap() -> MxnTiieSwap:
    return MxnTiieSwap(
        notional=Decimal("100000000"),  # 100M MXN
        fixed_rate=0.1100,              # 11.00%
        start_date=date(2025, 6, 15),
        end_date=date(2026, 6, 15),
        pay_receive_fixed=PayReceive.PAY,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_basic_pricing(sample_mxn_swap: MxnTiieSwap, mxn_market: MarketData):
    """Basic pricing returns a result with correct instrument_type and currency."""
    result = price_mxn_tiie_swap(sample_mxn_swap, mxn_market)
    assert result.instrument_type == "MXN_TIIE_SWAP"
    assert result.currency == Currency.MXN
    assert isinstance(result.present_value, Decimal)


def test_pay_vs_receive_opposite_sign(
    sample_mxn_swap: MxnTiieSwap, mxn_market: MarketData
):
    """Pay-fixed and receive-fixed produce opposite NPV signs."""
    pay_result = price_mxn_tiie_swap(sample_mxn_swap, mxn_market)

    receive_swap = sample_mxn_swap.model_copy(
        update={"pay_receive_fixed": PayReceive.RECEIVE}
    )
    recv_result = price_mxn_tiie_swap(receive_swap, mxn_market)

    assert pay_result.present_value == -recv_result.present_value


def test_missing_curve_raises(sample_mxn_swap: MxnTiieSwap, valuation_date: date):
    """Missing MXN-TIIE curve raises ValueError."""
    empty_market = MarketData(valuation_date=valuation_date)
    with pytest.raises(ValueError, match="MXN-TIIE"):
        price_mxn_tiie_swap(sample_mxn_swap, empty_market)


def test_details_include_leg_pvs(
    sample_mxn_swap: MxnTiieSwap, mxn_market: MarketData
):
    """Details include fixed_leg_pv and float_leg_pv."""
    result = price_mxn_tiie_swap(sample_mxn_swap, mxn_market)
    assert "fixed_leg_pv" in result.details
    assert "float_leg_pv" in result.details
    assert "number_of_periods" in result.details


def test_at_market_swap_near_zero_npv(
    valuation_date: date, mxn_tiie_curve: DiscountCurve
):
    """A swap where fixed rate equals the implied par rate has near-zero NPV.

    The par swap rate is the fixed rate that makes the swap NPV = 0.
    We compute it from the curve, then verify the pricer agrees.
    """
    from fi_claude.curves.interpolation import interpolate_discount_factor
    from fi_claude.curves.day_count import year_fraction
    from dateutil.relativedelta import relativedelta

    start = date(2025, 6, 15)
    end = date(2026, 6, 15)

    # Generate payment dates (monthly)
    payment_dates = []
    current = start + relativedelta(months=1)
    while current <= end:
        payment_dates.append(current)
        current = current + relativedelta(months=1)
    if not payment_dates or payment_dates[-1] != end:
        payment_dates.append(end)

    # Compute the par swap rate: sum(alpha_i * df_i * fwd_i) / sum(alpha_i * df_i)
    # which simplifies to (df_start - df_end) / sum(alpha_i * df_i)
    numerator = 0.0
    denominator = 0.0
    period_start = start
    for pd in payment_dates:
        alpha = year_fraction(period_start, pd, DayCountConvention.ACT_360)
        df_end = interpolate_discount_factor(mxn_tiie_curve, pd)
        denominator += alpha * df_end
        period_start = pd

    df_0 = interpolate_discount_factor(mxn_tiie_curve, start)
    df_n = interpolate_discount_factor(mxn_tiie_curve, end)
    numerator = df_0 - df_n

    par_rate = numerator / denominator

    # Build a swap at the par rate
    at_market_swap = MxnTiieSwap(
        notional=Decimal("100000000"),
        fixed_rate=par_rate,
        start_date=start,
        end_date=end,
        pay_receive_fixed=PayReceive.PAY,
    )

    market = MarketData(
        valuation_date=valuation_date,
        discount_curves={"MXN-TIIE": mxn_tiie_curve},
    )

    result = price_mxn_tiie_swap(at_market_swap, market)
    assert abs(float(result.present_value)) < 1.0  # < 1 MXN on 100M notional


def test_multi_period_cashflows(
    sample_mxn_swap: MxnTiieSwap, mxn_market: MarketData
):
    """Multi-period schedule generates correct number of cashflows.

    For a 1-year swap with monthly payments, we expect about 12 periods.
    The cashflows tuple contains both fixed and float cashflows, so
    total count should be approximately 2 * number_of_periods.
    """
    result = price_mxn_tiie_swap(sample_mxn_swap, mxn_market)
    n_periods = int(result.details["number_of_periods"])
    # 1-year monthly -> 12 periods
    assert 11 <= n_periods <= 13
    # cashflows = fixed + float
    assert len(result.cashflows) == 2 * n_periods


def test_one_year_monthly_generates_12_periods(
    mxn_market: MarketData,
):
    """A 1-year swap with monthly payments generates ~12 periods."""
    swap = MxnTiieSwap(
        notional=Decimal("50000000"),
        fixed_rate=0.1050,
        start_date=date(2025, 6, 15),
        end_date=date(2026, 6, 15),
        pay_receive_fixed=PayReceive.RECEIVE,
    )
    result = price_mxn_tiie_swap(swap, mxn_market)
    assert int(result.details["number_of_periods"]) == 12


def test_swap_defaults():
    """MxnTiieSwap uses correct default conventions."""
    swap = MxnTiieSwap(
        notional=Decimal("1000000"),
        fixed_rate=0.1100,
        start_date=date(2025, 6, 15),
        end_date=date(2026, 6, 15),
        pay_receive_fixed=PayReceive.PAY,
    )
    assert swap.day_count == DayCountConvention.ACT_360
    assert swap.currency == Currency.MXN
    assert swap.payment_frequency_months == 1
