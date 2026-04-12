"""Test BRL Pre-CDI swap pricer."""

from datetime import date
from decimal import Decimal

import pytest

from fi_claude.data.common import Currency, PayReceive
from fi_claude.data.market import MarketData
from fi_claude.data.instruments import BrlPreCdiSwap
from fi_claude.pricers.brl_pre_cdi import price_brl_pre_cdi_swap


def test_basic_pricing(sample_brl_swap: BrlPreCdiSwap, market_data: MarketData):
    result = price_brl_pre_cdi_swap(sample_brl_swap, market_data, business_days=252)
    assert result.instrument_type == "BRL_PRE_CDI_SWAP"
    assert result.currency == Currency.BRL
    assert isinstance(result.present_value, Decimal)


def test_pay_vs_receive_opposite_sign(sample_brl_swap: BrlPreCdiSwap, market_data: MarketData):
    pay_result = price_brl_pre_cdi_swap(sample_brl_swap, market_data, business_days=252)

    receive_swap = sample_brl_swap.model_copy(
        update={"pay_receive_fixed": PayReceive.RECEIVE}
    )
    recv_result = price_brl_pre_cdi_swap(receive_swap, market_data, business_days=252)

    assert pay_result.present_value == -recv_result.present_value


def test_missing_curve_raises(sample_brl_swap: BrlPreCdiSwap, valuation_date: date):
    empty_market = MarketData(valuation_date=valuation_date)
    with pytest.raises(ValueError, match="BRL-CDI"):
        price_brl_pre_cdi_swap(sample_brl_swap, empty_market, business_days=252)


def test_details_populated(sample_brl_swap: BrlPreCdiSwap, market_data: MarketData):
    result = price_brl_pre_cdi_swap(sample_brl_swap, market_data, business_days=252)
    assert "fixed_leg_pv" in result.details
    assert "float_leg_pv" in result.details
    assert "year_fraction" in result.details
    assert result.details["year_fraction"] == pytest.approx(1.0, abs=0.01)


def test_float_leg_pv_equals_notional_times_df_start(
    sample_brl_swap: BrlPreCdiSwap, market_data: MarketData
):
    """OpenGamma QR n.18 §4: float leg PV = N × P^D(t, t_0).

    The overnight compounded product telescopes so the float leg
    is worth notional × df(start_date).
    """
    result = price_brl_pre_cdi_swap(sample_brl_swap, market_data, business_days=252)
    df_start = result.details["df_start"]
    expected = float(sample_brl_swap.notional) * df_start
    assert result.details["float_leg_pv"] == pytest.approx(expected, rel=1e-8)


def test_par_rate_matches_curve():
    """At-market swap (NPV≈0) should have fixed rate ≈ implied curve rate.

    Par rate formula: r_par = (df_start / df_end)^(1/α) - 1
    """
    from fi_claude.data.curves import CurveNode, DiscountCurve, InterpolationMethod

    val = date(2025, 6, 15)
    # Curve with T=0 node so df_start = 1.0
    curve = DiscountCurve(
        reference_date=val,
        currency=Currency.BRL,
        nodes=(
            CurveNode(date=val, value=1.0),
            CurveNode(date=date(2026, 6, 15), value=0.88),
        ),
        interpolation=InterpolationMethod.LOG_LINEAR,
    )
    market = MarketData(
        valuation_date=val,
        discount_curves={"BRL-CDI": curve},
    )

    # Implied 1Y rate from df=0.88: r = (1/0.88)^(252/252) - 1 = 0.13636
    implied_rate = (1.0 / 0.88) - 1.0

    swap = BrlPreCdiSwap(
        notional=Decimal("10000000"),
        fixed_rate=implied_rate,
        start_date=val,
        end_date=date(2026, 6, 15),
        pay_receive_fixed=PayReceive.PAY,
    )
    result = price_brl_pre_cdi_swap(swap, market, business_days=252)

    # NPV should be ~0 for at-market swap
    assert abs(float(result.present_value)) < 100  # within BRL 100 on 10M notional
