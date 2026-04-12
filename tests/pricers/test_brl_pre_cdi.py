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
