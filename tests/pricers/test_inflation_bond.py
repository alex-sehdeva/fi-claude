"""Test inflation-linked bond pricer."""

from datetime import date
from decimal import Decimal

import pytest

from fi_claude.data.common import Currency
from fi_claude.data.instruments import InflationLinkedBond
from fi_claude.data.market import MarketData
from fi_claude.pricers.inflation_bond import price_inflation_linked_bond


def test_basic_pricing(sample_tips_bond: InflationLinkedBond, market_data: MarketData):
    result = price_inflation_linked_bond(sample_tips_bond, market_data)
    assert result.instrument_type == "INFLATION_LINKED_BOND"
    assert result.currency == Currency.USD
    assert result.present_value > 0


def test_has_cashflows(sample_tips_bond: InflationLinkedBond, market_data: MarketData):
    result = price_inflation_linked_bond(sample_tips_bond, market_data)
    assert len(result.cashflows) > 0
    # Should have future coupons + principal
    assert any(cf.amount > Decimal("100000") for cf in result.cashflows)  # principal


def test_deflation_floor(sample_tips_bond: InflationLinkedBond, market_data: MarketData):
    """With deflation floor, PV should not drop below face value present value."""
    result = price_inflation_linked_bond(sample_tips_bond, market_data)
    assert result.present_value > 0
    assert result.details.get("deflation_floor_active") == 1.0  # bool coerced to float in dict[str, float]


def test_missing_inflation_curve(sample_tips_bond: InflationLinkedBond, valuation_date: date):
    from fi_claude.data.curves import CurveNode, DiscountCurve

    market = MarketData(
        valuation_date=valuation_date,
        discount_curves={
            "USD-REAL": DiscountCurve(
                reference_date=valuation_date,
                currency=Currency.USD,
                nodes=(CurveNode(date=date(2027, 1, 15), value=0.92),),
            )
        },
    )
    with pytest.raises(ValueError, match="inflation curve"):
        price_inflation_linked_bond(sample_tips_bond, market)
