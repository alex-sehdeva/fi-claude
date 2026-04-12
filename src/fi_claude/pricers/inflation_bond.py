"""Inflation-linked bond pricer — pure CALCULATION.

Prices a bond whose principal and coupons are indexed to a CPI series.
Handles deflation floors (principal protected at par).

References:
    - Strata: DiscountingCapitalIndexedBondProductPricer
    - QuantLib: CPIBond pricing engine
    - US Treasury TIPS methodology
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fi_claude.curves.day_count import year_fraction
from fi_claude.curves.interpolation import interpolate_discount_factor
from fi_claude.data.common import Cashflow, Currency
from fi_claude.data.curves import InflationCurve
from fi_claude.data.instruments import InflationLinkedBond
from fi_claude.data.market import MarketData
from fi_claude.data.results import PricingResult


def price_inflation_linked_bond(
    bond: InflationLinkedBond,
    market: MarketData,
) -> PricingResult:
    """Price an inflation-linked bond.

    Pure function: (InflationLinkedBond, MarketData) → PricingResult.
    """
    curve_key = f"{bond.currency.value}-REAL"
    discount_curve = market.discount_curves.get(curve_key)
    if discount_curve is None:
        msg = f"MarketData missing '{curve_key}' discount curve"
        raise ValueError(msg)

    inflation_curve = next(iter(market.inflation_curves.values()), None)
    if inflation_curve is None:
        msg = "MarketData missing inflation curve"
        raise ValueError(msg)

    valuation = market.valuation_date
    cashflows: list[Cashflow] = []
    total_pv = 0.0

    # Price each coupon
    for entry in bond.coupon_schedule:
        if entry.payment_date <= valuation:
            continue

        index_ratio = _index_ratio(
            bond, inflation_curve, entry.payment_date
        )
        coupon_amount = float(bond.face_value) * bond.real_coupon_rate * index_ratio
        yf = year_fraction(entry.accrual_start, entry.accrual_end, bond.day_count)
        period_coupon = coupon_amount * yf

        df = interpolate_discount_factor(discount_curve, entry.payment_date)
        total_pv += period_coupon * df

        cashflows.append(Cashflow(
            payment_date=entry.payment_date,
            amount=Decimal(str(round(period_coupon, 2))),
            currency=bond.currency,
        ))

    # Principal at maturity
    if bond.maturity_date > valuation:
        index_ratio = _index_ratio(bond, inflation_curve, bond.maturity_date)
        redemption = float(bond.face_value) * index_ratio

        if bond.deflation_floor:
            redemption = max(redemption, float(bond.face_value))

        df_maturity = interpolate_discount_factor(discount_curve, bond.maturity_date)
        total_pv += redemption * df_maturity

        cashflows.append(Cashflow(
            payment_date=bond.maturity_date,
            amount=Decimal(str(round(redemption, 2))),
            currency=bond.currency,
        ))

    return PricingResult(
        instrument_type="INFLATION_LINKED_BOND",
        valuation_date=valuation,
        currency=bond.currency,
        present_value=Decimal(str(round(total_pv, 2))),
        cashflows=tuple(cashflows),
        details={
            "base_cpi": bond.base_cpi,
            "deflation_floor_active": bond.deflation_floor,
        },
    )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _index_ratio(
    bond: InflationLinkedBond,
    inflation_curve: InflationCurve,
    target: date,
) -> float:
    """CPI index ratio: current_cpi / base_cpi.

    Returns >= 1.0 if deflation floor applies and CPI has fallen.
    """
    from fi_claude.curves.interpolation import interpolate_discount_factor as _interp
    from fi_claude.data.curves import DiscountCurve, CurveNode, InterpolationMethod

    # Build a temporary "curve" from inflation nodes for interpolation reuse.
    # This is a pure transformation — no side effects.
    temp_curve = DiscountCurve(
        reference_date=inflation_curve.reference_date,
        currency="USD",  # placeholder, not used in interpolation
        nodes=inflation_curve.nodes,
        interpolation=inflation_curve.interpolation,
    )
    current_cpi = _interp(temp_curve, target)
    ratio = current_cpi / bond.base_cpi

    if bond.deflation_floor:
        ratio = max(ratio, 1.0)

    return ratio
