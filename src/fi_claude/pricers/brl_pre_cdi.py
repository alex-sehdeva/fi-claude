"""BRL Pre-CDI swap pricer — pure CALCULATION.

A Pre-CDI swap has:
  - Fixed leg: pre-fixed rate compounded over BUS/252
  - Float leg: CDI overnight rate compounded daily over BUS/252

The present value is the difference between fixed and float leg NPVs,
both discounted on the CDI curve.

Convention references:
  - B3 (Brazilian exchange) DI-future specifications
  - Strata: BRL-CDI index (partial support)
  - QuantLib-Ext: BRLCdiSwap in QuantExt
"""

from __future__ import annotations

from decimal import Decimal

from fi_claude.curves.day_count import year_fraction
from fi_claude.curves.interpolation import interpolate_discount_factor
from fi_claude.data.common import Currency, DayCountConvention, PayReceive
from fi_claude.data.instruments import BrlPreCdiSwap
from fi_claude.data.market import MarketData
from fi_claude.data.results import PricingResult


def price_brl_pre_cdi_swap(
    swap: BrlPreCdiSwap,
    market: MarketData,
    business_days: int,
) -> PricingResult:
    """Price a BRL Pre x CDI swap.

    Pure function: (BrlPreCdiSwap, MarketData, int) → PricingResult.

    business_days: number of business days between start and end dates
    (requires a Brazilian holiday calendar to compute — that's the caller's job).
    """
    curve = market.discount_curves.get("BRL-CDI")
    if curve is None:
        msg = "MarketData missing 'BRL-CDI' discount curve"
        raise ValueError(msg)

    # Year fraction under BUS/252
    yf = year_fraction(
        swap.start_date, swap.end_date, DayCountConvention.BUS_252, business_days
    )

    # Fixed leg: notional × (1 + fixed_rate)^yf
    fixed_leg_fv = float(swap.notional) * (1.0 + swap.fixed_rate) ** yf

    # Discount factor to start and end dates
    df_start = interpolate_discount_factor(curve, swap.start_date)
    df_end = interpolate_discount_factor(curve, swap.end_date)

    # Float leg PV at valuation: notional × (df_start / df_end) - notional
    # (the CDI leg is worth par at start; its PV is driven by the curve ratio)
    float_leg_pv = float(swap.notional) * (df_start / df_end)

    # Fixed leg PV: discount the future value back
    fixed_leg_pv = fixed_leg_fv * df_end

    # NPV from the perspective of the fixed-rate payer
    npv_pay_fixed = float_leg_pv - fixed_leg_pv

    # Flip sign if we receive fixed
    sign = 1.0 if swap.pay_receive_fixed == PayReceive.PAY else -1.0
    pv = Decimal(str(round(sign * npv_pay_fixed, 2)))

    return PricingResult(
        instrument_type="BRL_PRE_CDI_SWAP",
        valuation_date=market.valuation_date,
        currency=Currency.BRL,
        present_value=pv,
        details={
            "fixed_leg_pv": round(fixed_leg_pv, 2),
            "float_leg_pv": round(float_leg_pv, 2),
            "year_fraction": round(yf, 6),
            "df_start": round(df_start, 8),
            "df_end": round(df_end, 8),
        },
    )
