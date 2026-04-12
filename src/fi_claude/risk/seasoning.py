"""Portfolio seasoning statistics — pure CALCULATIONS.

Computes the expected P&L decomposition and risk evolution from the
passage of time, using the standard "roll curves forward" methodology.

Decomposition:
  The curve is re-anchored to the horizon date (same shape, same discount
  factor values, but node dates shift forward by the horizon). The instrument
  ages — its cashflows are now closer to the new reference date, reading off
  higher (shorter-tenor) parts of the curve.

  total_theta = PV(t+h, rolled_curves) - PV(t, curves)
  carry       = sum of cashflows in (t, t+h]
  rolldown    = total_theta - carry

Risk evolution:
  dv01_change = DV01(t+h) - DV01(t)       # rate sensitivity drift
  cs01_change = CS01(t+h) - CS01(t)       # spread sensitivity drift

All functions are pure: (pricer, MarketData, horizon) → result.
The pricer argument is a Callable[[MarketData], PricingResult] with the
instrument and any extra args already bound (via functools.partial or lambda).
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal
from typing import Callable

from pydantic import BaseModel

from fi_claude.data.common import Cashflow
from fi_claude.data.curves import CurveNode, DiscountCurve, FxForwardCurve, InflationCurve
from fi_claude.data.market import MarketData
from fi_claude.data.results import PricingResult


# ---------------------------------------------------------------------------
# Result DATA models
# ---------------------------------------------------------------------------


class RiskSnapshot(BaseModel, frozen=True):
    """DV01 and CS01 at a single point in time."""

    dv01: dict[str, float] = {}   # {curve_key: dv01_value}
    cs01: dict[str, float] = {}   # {curve_key: cs01_value}


class HorizonResult(BaseModel, frozen=True):
    """Seasoning statistics for a single time horizon."""

    horizon_label: str             # e.g. "1D", "1W"
    horizon_days: int
    base_date: date
    horizon_date: date

    # P&L decomposition
    base_pv: float
    horizon_pv: float
    total_theta: float             # horizon_pv - base_pv
    carry: float                   # cashflows received in (base, horizon]
    rolldown: float                # total_theta - carry

    # Annualized
    theta_annual: float            # total_theta * 365 / horizon_days
    carry_annual: float
    rolldown_annual: float

    # Risk at base date
    base_risk: RiskSnapshot

    # Risk at horizon date (on rolled market)
    horizon_risk: RiskSnapshot

    # Risk evolution
    dv01_change: dict[str, float]  # horizon - base, per curve
    cs01_change: dict[str, float]


class SeasoningReport(BaseModel, frozen=True):
    """Complete seasoning report across multiple horizons."""

    instrument_type: str
    currency: str
    horizons: tuple[HorizonResult, ...]


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------


def compute_seasoning(
    pricer: Callable[[MarketData], PricingResult],
    market: MarketData,
    horizon_days: int,
    horizon_label: str = "",
    rate_curve_keys: tuple[str, ...] = (),
    credit_curve_keys: tuple[str, ...] = (),
    bump_bps: float = 1.0,
) -> HorizonResult:
    """Compute seasoning statistics for a single horizon.

    Pure function:
        (pricer, MarketData, horizon_days, ...) → HorizonResult

    The "hold curve shape constant" convention: all curve node dates
    shift forward by horizon_days, keeping discount factor values
    unchanged. The instrument's cashflows stay at their absolute dates,
    but now read off shorter-tenor points on the rolled curve.

    Args:
        pricer: Callable that takes MarketData and returns PricingResult.
                Bind instrument-specific args beforehand:
                    pricer = lambda m: price_tba(tba, m)
        market: Base market data snapshot.
        horizon_days: Calendar days to advance (1 = overnight, 7 = 1 week).
        horizon_label: Display label (e.g. "1D", "1W"). Auto-generated if empty.
        rate_curve_keys: Curve keys for DV01 calculation.
        credit_curve_keys: Curve keys for CS01 calculation.
        bump_bps: Bump size for DV01/CS01 (default 1bp).
    """
    base_date = market.valuation_date
    horizon_date = base_date + timedelta(days=horizon_days)
    label = horizon_label or f"{horizon_days}D"

    # --- Price at base ---
    base_result = pricer(market)
    base_pv = float(base_result.present_value)

    # --- Roll curves forward and price at horizon ---
    horizon_market = roll_market_forward(market, horizon_days)
    horizon_result = pricer(horizon_market)
    horizon_pv = float(horizon_result.present_value)

    total_theta = horizon_pv - base_pv

    # --- Carry: cashflows that pay during (base, horizon] ---
    carry = _compute_carry(base_result.cashflows, base_date, horizon_date)

    # --- Rolldown: residual after carry ---
    rolldown = total_theta - carry

    # --- Annualize ---
    ann_factor = 365.0 / horizon_days if horizon_days > 0 else 0.0
    theta_annual = total_theta * ann_factor
    carry_annual = carry * ann_factor
    rolldown_annual = rolldown * ann_factor

    # --- DV01 at base and horizon ---
    base_dv01 = _compute_dv01s(pricer, market, rate_curve_keys, bump_bps)
    horizon_dv01 = _compute_dv01s(pricer, horizon_market, rate_curve_keys, bump_bps)
    dv01_change = {k: round(horizon_dv01.get(k, 0.0) - base_dv01.get(k, 0.0), 4)
                   for k in set(base_dv01) | set(horizon_dv01)}

    # --- CS01 at base and horizon ---
    base_cs01 = _compute_dv01s(pricer, market, credit_curve_keys, bump_bps)
    horizon_cs01 = _compute_dv01s(pricer, horizon_market, credit_curve_keys, bump_bps)
    cs01_change = {k: round(horizon_cs01.get(k, 0.0) - base_cs01.get(k, 0.0), 4)
                   for k in set(base_cs01) | set(horizon_cs01)}

    return HorizonResult(
        horizon_label=label,
        horizon_days=horizon_days,
        base_date=base_date,
        horizon_date=horizon_date,
        base_pv=round(base_pv, 2),
        horizon_pv=round(horizon_pv, 2),
        total_theta=round(total_theta, 2),
        carry=round(carry, 2),
        rolldown=round(rolldown, 2),
        theta_annual=round(theta_annual, 2),
        carry_annual=round(carry_annual, 2),
        rolldown_annual=round(rolldown_annual, 2),
        base_risk=RiskSnapshot(dv01=base_dv01, cs01=base_cs01),
        horizon_risk=RiskSnapshot(dv01=horizon_dv01, cs01=horizon_cs01),
        dv01_change=dv01_change,
        cs01_change=cs01_change,
    )


def season_portfolio(
    pricer: Callable[[MarketData], PricingResult],
    market: MarketData,
    horizons: tuple[int, ...] = (1, 7),
    rate_curve_keys: tuple[str, ...] = (),
    credit_curve_keys: tuple[str, ...] = (),
    bump_bps: float = 1.0,
) -> SeasoningReport:
    """Compute seasoning across multiple horizons (e.g., 1D and 1W).

    Pure function: (pricer, MarketData, horizons) → SeasoningReport.

    Usage:
        pricer = lambda m: price_tba(tba, m)
        report = season_portfolio(pricer, market,
                    horizons=(1, 7),
                    rate_curve_keys=("USD",),
                    credit_curve_keys=("USD-SPREAD",))
    """
    labels = {1: "1D", 7: "1W", 14: "2W", 30: "1M", 90: "3M", 365: "1Y"}

    base_result = pricer(market)

    results = tuple(
        compute_seasoning(
            pricer=pricer,
            market=market,
            horizon_days=h,
            horizon_label=labels.get(h, f"{h}D"),
            rate_curve_keys=rate_curve_keys,
            credit_curve_keys=credit_curve_keys,
            bump_bps=bump_bps,
        )
        for h in horizons
    )

    return SeasoningReport(
        instrument_type=base_result.instrument_type,
        currency=base_result.currency.value,
        horizons=results,
    )


# ---------------------------------------------------------------------------
# Curve rolling — pure CALCULATIONS
# ---------------------------------------------------------------------------


def roll_market_forward(market: MarketData, days: int) -> MarketData:
    """Roll the entire market forward by `days` calendar days.

    Every curve's reference_date and node dates shift forward by `days`.
    Discount factor values are preserved — the curve keeps its shape
    in tenor space. The valuation date advances by the same amount.

    This is the standard "hold curve shape constant" assumption for
    theta/rolldown decomposition.
    """
    delta = timedelta(days=days)
    new_val = market.valuation_date + delta

    # Roll discount curves
    new_dc = {
        k: _roll_discount_curve(c, delta)
        for k, c in market.discount_curves.items()
    }

    # Roll inflation curves
    new_ic = {
        k: _roll_inflation_curve(c, delta)
        for k, c in market.inflation_curves.items()
    }

    # Roll FX forward curves
    new_fx = {
        k: _roll_fx_curve(c, delta)
        for k, c in market.fx_curves.items()
    }

    return market.model_copy(update={
        "valuation_date": new_val,
        "discount_curves": new_dc,
        "inflation_curves": new_ic,
        "fx_curves": new_fx,
    })


def _roll_discount_curve(curve: DiscountCurve, delta: timedelta) -> DiscountCurve:
    """Shift a discount curve forward in time, preserving DF values."""
    return curve.model_copy(update={
        "reference_date": curve.reference_date + delta,
        "nodes": tuple(
            CurveNode(date=n.date + delta, value=n.value)
            for n in curve.nodes
        ),
    })


def _roll_inflation_curve(curve: InflationCurve, delta: timedelta) -> InflationCurve:
    """Shift an inflation curve forward, preserving CPI values."""
    return curve.model_copy(update={
        "reference_date": curve.reference_date + delta,
        "nodes": tuple(
            CurveNode(date=n.date + delta, value=n.value)
            for n in curve.nodes
        ),
    })


def _roll_fx_curve(curve: FxForwardCurve, delta: timedelta) -> FxForwardCurve:
    """Shift an FX forward curve forward, preserving forward points."""
    return curve.model_copy(update={
        "reference_date": curve.reference_date + delta,
        "nodes": tuple(
            CurveNode(date=n.date + delta, value=n.value)
            for n in curve.nodes
        ),
    })


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _compute_carry(
    cashflows: tuple[Cashflow, ...],
    start: date,
    end: date,
) -> float:
    """Sum cashflows that pay in the window (start, end].

    Carry = income received from holding the position.
    Cashflows on the start date are excluded (already settled);
    cashflows on or before the end date are included.
    """
    return sum(
        float(cf.amount)
        for cf in cashflows
        if start < cf.payment_date <= end
    )


def _compute_dv01s(
    pricer: Callable[[MarketData], PricingResult],
    market: MarketData,
    curve_keys: tuple[str, ...],
    bump_bps: float,
) -> dict[str, float]:
    """Compute DV01 for each specified curve.

    DV01 = PV(bumped) - PV(base) for a parallel bump of bump_bps.
    """
    if not curve_keys:
        return {}

    base_pv = float(pricer(market).present_value)
    result = {}

    for key in curve_keys:
        if key not in market.discount_curves:
            continue
        bumped_market = _parallel_bump(market, key, bump_bps)
        bumped_pv = float(pricer(bumped_market).present_value)
        result[key] = round(bumped_pv - base_pv, 4)

    return result


def _parallel_bump(market: MarketData, curve_key: str, bump_bps: float) -> MarketData:
    """Apply a parallel rate bump to one curve. Returns new MarketData."""
    curve = market.discount_curves[curve_key]
    ref = market.valuation_date

    bumped_nodes = tuple(
        CurveNode(
            date=node.date,
            value=node.value * math.exp(
                -bump_bps / 10_000 * (node.date - ref).days / 365.25
            ),
        )
        for node in curve.nodes
    )

    new_curves = {
        **market.discount_curves,
        curve_key: curve.model_copy(update={"nodes": bumped_nodes}),
    }
    return market.model_copy(update={"discount_curves": new_curves})
