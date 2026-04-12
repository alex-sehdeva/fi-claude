"""Test TBA pricer."""

from datetime import date
from decimal import Decimal

import pytest

from fi_claude.data.common import Currency
from fi_claude.data.instruments import TbaContract
from fi_claude.data.market import MarketData
from fi_claude.pricers.tba import price_tba, _project_cashflows_cpr


def test_basic_pricing(sample_tba: TbaContract, market_data: MarketData):
    result = price_tba(sample_tba, market_data)
    assert result.instrument_type == "TBA"
    assert result.currency == Currency.USD
    assert result.present_value > 0


def test_cashflow_projection():
    """Test the CPR model produces reasonable cashflows."""
    cashflows = _project_cashflows_cpr(
        face=1_000_000,
        coupon_rate=0.055,
        term_months=360,
        settlement=date(2025, 7, 15),
        pool_factor=1.0,
        cpr=0.08,
    )
    # Should have many cashflows (360 months minus early payoff)
    assert len(cashflows) > 100
    # First cashflow should be roughly monthly payment
    first_cf = cashflows[0][1]
    assert 5000 < first_cf < 15000  # reasonable monthly range for $1M 30yr 5.5%


def test_higher_cpr_means_less_total_principal():
    """Higher CPR = faster prepayment = lower total interest paid."""
    low_cpr = _project_cashflows_cpr(
        face=1_000_000, coupon_rate=0.055, term_months=360,
        settlement=date(2025, 7, 15), pool_factor=1.0, cpr=0.04,
    )
    high_cpr = _project_cashflows_cpr(
        face=1_000_000, coupon_rate=0.055, term_months=360,
        settlement=date(2025, 7, 15), pool_factor=1.0, cpr=0.30,
    )
    total_low = sum(row[1] for row in low_cpr)
    total_high = sum(row[1] for row in high_cpr)
    # Higher prepayment = less total interest paid over the life
    assert total_high < total_low


def test_missing_usd_curve(sample_tba: TbaContract, valuation_date: date):
    market = MarketData(valuation_date=valuation_date)
    with pytest.raises(ValueError, match="USD"):
        price_tba(sample_tba, market)


def test_pool_factor_reduces_cashflows():
    """Lower pool factor = less remaining principal."""
    full = _project_cashflows_cpr(
        face=1_000_000, coupon_rate=0.055, term_months=360,
        settlement=date(2025, 7, 15), pool_factor=1.0, cpr=0.08,
    )
    half = _project_cashflows_cpr(
        face=1_000_000, coupon_rate=0.055, term_months=360,
        settlement=date(2025, 7, 15), pool_factor=0.5, cpr=0.08,
    )
    # Half the pool factor → roughly half the first cashflow
    # Compare total cashflow (index 1) for first period
    assert half[0][1] < full[0][1]
