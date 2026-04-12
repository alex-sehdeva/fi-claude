"""Cross-currency basis swap pricer — pure CALCULATION.

Prices a swap where both legs float in different currencies,
with optional initial/final notional exchanges and MtM resets.

References:
    - Strata: Swap with cross-currency legs + FxReset
    - QuantLib: CrossCurrencyBasisSwapRateHelper (curve bootstrapping only)
    - QuantLib issue #2201 (no turnkey pricer)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fi_claude.curves.interpolation import interpolate_discount_factor
from fi_claude.data.common import Cashflow, Currency
from fi_claude.data.instruments import XccyBasisSwap, XccyLeg
from fi_claude.data.market import MarketData
from fi_claude.data.results import PricingResult


def price_xccy_basis_swap(
    swap: XccyBasisSwap,
    market: MarketData,
) -> PricingResult:
    """Price a cross-currency basis swap.

    Pure function: (XccyBasisSwap, MarketData) → PricingResult.

    Result is expressed in the near leg's currency.
    """
    near = swap.near_leg
    far = swap.far_leg

    near_curve = market.discount_curves.get(near.currency.value)
    far_curve = market.discount_curves.get(far.currency.value)
    if near_curve is None or far_curve is None:
        msg = f"MarketData missing discount curves for {near.currency}/{far.currency}"
        raise ValueError(msg)

    fx_key = f"{far.currency.value}/{near.currency.value}"
    fx_spot = market.fx_spot_rates.get(fx_key)
    if fx_spot is None:
        msg = f"MarketData missing FX spot rate for {fx_key}"
        raise ValueError(msg)

    valuation = market.valuation_date
    cashflows: list[Cashflow] = []

    # Near leg PV (in near currency)
    near_pv = _leg_pv(near, near_curve, swap.start_date, swap.end_date, valuation, cashflows)

    # Far leg PV (in far currency, then converted)
    far_cashflows: list[Cashflow] = []
    far_pv_foreign = _leg_pv(far, far_curve, swap.start_date, swap.end_date, valuation, far_cashflows)
    far_pv_domestic = far_pv_foreign * fx_spot

    # Notional exchanges
    exchange_pv = 0.0
    if swap.initial_exchange and swap.start_date > valuation:
        df_near_start = interpolate_discount_factor(near_curve, swap.start_date)
        df_far_start = interpolate_discount_factor(far_curve, swap.start_date)
        exchange_pv -= float(near.notional) * df_near_start
        exchange_pv += float(far.notional) * df_far_start * fx_spot

    if swap.final_exchange and swap.end_date > valuation:
        df_near_end = interpolate_discount_factor(near_curve, swap.end_date)
        df_far_end = interpolate_discount_factor(far_curve, swap.end_date)
        exchange_pv += float(near.notional) * df_near_end
        exchange_pv -= float(far.notional) * df_far_end * fx_spot

    total_pv = near_pv - far_pv_domestic + exchange_pv

    return PricingResult(
        instrument_type="XCCY_BASIS_SWAP",
        valuation_date=valuation,
        currency=near.currency,
        present_value=Decimal(str(round(total_pv, 2))),
        cashflows=tuple(cashflows + far_cashflows),
        details={
            "near_leg_pv": round(near_pv, 2),
            "far_leg_pv_domestic": round(far_pv_domestic, 2),
            "far_leg_pv_foreign": round(far_pv_foreign, 2),
            "exchange_pv": round(exchange_pv, 2),
            "fx_spot": fx_spot,
        },
    )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _leg_pv(
    leg: XccyLeg,
    curve: object,  # DiscountCurve
    start: date,
    end: date,
    valuation: date,
    cashflows_out: list[Cashflow],
) -> float:
    """Estimate the PV of a floating leg using the forward rate implied by the curve.

    Simplified: each period's forward rate ≈ (df_start/df_end - 1) + spread.
    """
    from dateutil.relativedelta import relativedelta  # type: ignore[import-untyped]

    pv = 0.0
    period_start = start
    freq = leg.payment_frequency_months

    while period_start < end:
        period_end = min(period_start + relativedelta(months=freq), end)
        payment_date = period_end

        if payment_date <= valuation:
            period_start = period_end
            continue

        df_start = interpolate_discount_factor(curve, period_start)  # type: ignore[arg-type]
        df_end = interpolate_discount_factor(curve, period_end)  # type: ignore[arg-type]
        df_pay = interpolate_discount_factor(curve, payment_date)  # type: ignore[arg-type]

        # Forward rate for the period
        if df_end > 0:
            fwd_rate = (df_start / df_end - 1.0)
        else:
            fwd_rate = 0.0

        spread_accrual = (leg.spread_bps / 10_000) * (period_end - period_start).days / 360.0
        period_cashflow = float(leg.notional) * (fwd_rate + spread_accrual)

        pv += period_cashflow * df_pay

        cashflows_out.append(Cashflow(
            payment_date=payment_date,
            amount=Decimal(str(round(period_cashflow, 2))),
            currency=leg.currency,
        ))

        period_start = period_end

    return pv
