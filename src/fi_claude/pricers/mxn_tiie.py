"""MXN TIIE swap pricer — pure CALCULATION.

A TIIE swap has:
  - Fixed leg: fixed rate applied over ACT/360 day-count
  - Float leg: TIIE 28-day reference rate implied from the discount curve

Both legs pay at the same frequency (typically 28-day lunar months),
unlike USD swaps where fixed is semi-annual and float is quarterly.

Convention references:
  - Banxico (Banco de Mexico) TIIE specifications
  - ISDA 2006 definitions for ACT/360
  - Mexican Derivatives Exchange (MexDer) swap conventions
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from fi_claude.curves.day_count import year_fraction
from fi_claude.curves.interpolation import interpolate_discount_factor
from fi_claude.data.common import Cashflow, Currency, DayCountConvention, PayReceive
from fi_claude.data.instruments import MxnTiieSwap
from fi_claude.data.market import MarketData
from fi_claude.data.results import PricingResult


def _generate_payment_dates(start: date, end: date, frequency_months: int) -> list[date]:
    """Generate payment dates from start to end at the given monthly frequency.

    Pure function: (date, date, int) -> list[date].
    Returns dates starting from start + frequency through end (inclusive).
    """
    dates = []
    current = start + relativedelta(months=frequency_months)
    while current <= end:
        dates.append(current)
        current = current + relativedelta(months=frequency_months)
    # Ensure end date is included as the final payment date
    if not dates or dates[-1] != end:
        dates.append(end)
    return dates


def price_mxn_tiie_swap(
    swap: MxnTiieSwap,
    market: MarketData,
) -> PricingResult:
    """Price a MXN TIIE interest rate swap.

    Pure function: (MxnTiieSwap, MarketData) -> PricingResult.

    Uses the MXN-TIIE discount curve to compute forward rates and
    discount cashflows. Both legs use ACT/360 day count.
    """
    curve = market.discount_curves.get("MXN-TIIE")
    if curve is None:
        msg = "MarketData missing 'MXN-TIIE' discount curve"
        raise ValueError(msg)

    notional = float(swap.notional)
    payment_dates = _generate_payment_dates(
        swap.start_date, swap.end_date, swap.payment_frequency_months
    )

    fixed_leg_pv = 0.0
    float_leg_pv = 0.0
    fixed_cashflows: list[Cashflow] = []
    float_cashflows: list[Cashflow] = []

    # Walk through each period [t_{i-1}, t_i]
    period_start = swap.start_date
    for payment_date in payment_dates:
        # Year fraction for this period under ACT/360
        alpha = year_fraction(period_start, payment_date, DayCountConvention.ACT_360)

        # Discount factors
        df_start = interpolate_discount_factor(curve, period_start)
        df_end = interpolate_discount_factor(curve, payment_date)

        # Fixed cashflow: N * fixed_rate * alpha
        fixed_cf = notional * swap.fixed_rate * alpha
        fixed_leg_pv += fixed_cf * df_end

        # Forward rate: df(t_{i-1}) / df(t_i) - 1, then annualize via alpha
        # forward_rate * alpha = df(t_{i-1}) / df(t_i) - 1
        if df_end > 0:
            forward_rate_accrual = (df_start / df_end) - 1.0
        else:
            forward_rate_accrual = 0.0

        # Float cashflow: N * forward_rate * alpha = N * (df_start/df_end - 1)
        float_cf = notional * forward_rate_accrual
        float_leg_pv += float_cf * df_end

        fixed_cashflows.append(
            Cashflow(
                payment_date=payment_date,
                amount=Decimal(str(round(fixed_cf, 2))),
                currency=Currency.MXN,
            )
        )
        float_cashflows.append(
            Cashflow(
                payment_date=payment_date,
                amount=Decimal(str(round(float_cf, 2))),
                currency=Currency.MXN,
            )
        )

        period_start = payment_date

    # NPV from the perspective of the fixed-rate payer
    npv_pay_fixed = float_leg_pv - fixed_leg_pv

    # Flip sign if we receive fixed
    sign = 1.0 if swap.pay_receive_fixed == PayReceive.PAY else -1.0
    pv = Decimal(str(round(sign * npv_pay_fixed, 2)))

    # Combine all cashflows for the result (fixed then float)
    all_cashflows = tuple(fixed_cashflows + float_cashflows)

    return PricingResult(
        instrument_type="MXN_TIIE_SWAP",
        valuation_date=market.valuation_date,
        currency=Currency.MXN,
        present_value=pv,
        cashflows=all_cashflows,
        details={
            "fixed_leg_pv": round(fixed_leg_pv, 2),
            "float_leg_pv": round(float_leg_pv, 2),
            "number_of_periods": len(payment_dates),
        },
    )
