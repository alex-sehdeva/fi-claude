"""Market shock specifications — pure DATA + pure CALCULATIONS.

A Shock is DATA describing a perturbation. Applying a shock is a CALCULATION
that produces a new MarketData. Shocks compose via `+` (ShockSet).

Design principles:
  - Shocks are declarative: they say WHAT to perturb, not HOW to iterate
  - CIP coherence: rate shocks auto-propagate to FX forwards when requested
  - Composable: ShockSet([rate_shock, fx_shock]) applies atomically
  - Ergonomic: `parallel(+25)`, `steepen(2s=-10, 10s=+15)`, `twist(pivot=5y)`

Covered Interest Parity (CIP):
  F(t) / S = df_quote(t) / df_base(t)
  When a rate curve is shocked, FX forwards must adjust to stay CIP-consistent
  unless explicitly overridden.
"""

from __future__ import annotations

import math
from datetime import date
from enum import Enum
from typing import Callable

from pydantic import BaseModel

from fi_claude.data.curves import CurveNode, DiscountCurve, FxForwardCurve, InflationCurve
from fi_claude.data.market import MarketData


# ---------------------------------------------------------------------------
# Shock shape functions — pure CALCULATIONS
#
# Each takes (years_to_node, **params) → bump_in_bps for that node.
# This is where the math lives, completely decoupled from curve plumbing.
# ---------------------------------------------------------------------------


def _parallel(years: float, *, bps: float) -> float:
    """Constant bump across all tenors."""
    return bps


def _steepen(years: float, *, short_bps: float, long_bps: float,
             short_years: float, long_years: float) -> float:
    """Linear interpolation from short_bps at short_years to long_bps at long_years."""
    if years <= short_years:
        return short_bps
    if years >= long_years:
        return long_bps
    t = (years - short_years) / (long_years - short_years)
    return short_bps + t * (long_bps - short_bps)


def _twist(years: float, *, pivot_years: float, short_bps: float, long_bps: float) -> float:
    """Rotate around a pivot tenor: short end moves one way, long end the other."""
    if years <= pivot_years:
        # Linear from short_bps at 0y to 0 at pivot
        t = years / pivot_years if pivot_years > 0 else 0.0
        return short_bps * (1.0 - t)
    else:
        # Linear from 0 at pivot to long_bps at 30y
        t = (years - pivot_years) / (30.0 - pivot_years) if pivot_years < 30.0 else 0.0
        return long_bps * t


def _point(years: float, *, target_years: float, bps: float, width: float) -> float:
    """Bump concentrated around a single tenor (Gaussian-ish)."""
    dist = abs(years - target_years)
    if dist > 3 * width:
        return 0.0
    return bps * math.exp(-0.5 * (dist / width) ** 2)


# ---------------------------------------------------------------------------
# Shock DATA models — frozen, composable
# ---------------------------------------------------------------------------


class ShockType(str, Enum):
    PARALLEL = "PARALLEL"
    STEEPEN = "STEEPEN"
    FLATTEN = "FLATTEN"       # steepen with inverted sign
    TWIST = "TWIST"
    POINT = "POINT"
    CUSTOM = "CUSTOM"         # user-supplied per-node bps


class CurveShock(BaseModel, frozen=True):
    """A shock applied to one or more discount/rate curves.

    Specify WHAT to shock and HOW — applying it is a separate calculation.

    Examples:
        CurveShock(curves=["USD"], type=ShockType.PARALLEL, bps=25)
        CurveShock(curves=["USD"], type=ShockType.STEEPEN, short_bps=-10, long_bps=15)
        CurveShock(curves=["BRL-CDI"], type=ShockType.POINT, target_years=2.0, bps=50)
        CurveShock(curves=["USD", "EUR"], type=ShockType.CUSTOM, node_bps={0.25: 5, 1: 10, 5: 20})
    """

    curves: tuple[str, ...]           # curve keys to shock (e.g., ("USD", "EUR"))
    type: ShockType
    bps: float = 0.0                  # for PARALLEL, POINT
    short_bps: float = 0.0            # for STEEPEN/FLATTEN/TWIST
    long_bps: float = 0.0             # for STEEPEN/FLATTEN/TWIST
    short_years: float = 0.25         # for STEEPEN/FLATTEN
    long_years: float = 30.0          # for STEEPEN/FLATTEN
    pivot_years: float = 5.0          # for TWIST
    target_years: float = 5.0         # for POINT
    width: float = 0.5                # for POINT (Gaussian width in years)
    node_bps: dict[float, float] = {} # for CUSTOM: {years: bps}


class FxSpotShock(BaseModel, frozen=True):
    """Shock to FX spot rates.

    Example: FxSpotShock(pairs=("EUR/USD",), pct=2.0)  → EUR/USD +2%
    """

    pairs: tuple[str, ...]
    pct: float = 0.0          # percentage change (e.g., 2.0 = +2%)
    absolute: float = 0.0     # absolute change in spot (e.g., 0.05)


class InflationShock(BaseModel, frozen=True):
    """Shock to inflation/CPI curves.

    Example: InflationShock(curves=("US-CPI",), level_bps=50)  → CPI +50bps
    """

    curves: tuple[str, ...]
    level_bps: float = 0.0    # parallel shift to CPI index levels (in bps of level)


class CipPolicy(str, Enum):
    """How to handle CIP when rate curves are shocked."""

    ENFORCE = "ENFORCE"       # adjust FX forwards to maintain CIP
    IGNORE = "IGNORE"         # shock rates without touching FX
    BREAK = "BREAK"           # explicitly break CIP (stress test)


class ShockSet(BaseModel, frozen=True):
    """A coherent set of market shocks applied atomically.

    This is the top-level object you submit for repricing.
    Compose shocks freely — CIP policy controls cross-asset coherence.

    Usage:
        scenario = ShockSet(
            label="Fed +25, EUR basis tightens",
            rate_shocks=(
                CurveShock(curves=("USD",), type=ShockType.PARALLEL, bps=25),
                CurveShock(curves=("EUR",), type=ShockType.STEEPEN, short_bps=0, long_bps=10),
            ),
            fx_shocks=(
                FxSpotShock(pairs=("EUR/USD",), pct=-1.5),
            ),
            cip=CipPolicy.ENFORCE,
        )
        shocked_market = apply_shocks(base_market, scenario)
        result = price_instrument(instrument, shocked_market)
    """

    label: str = ""
    rate_shocks: tuple[CurveShock, ...] = ()
    fx_shocks: tuple[FxSpotShock, ...] = ()
    inflation_shocks: tuple[InflationShock, ...] = ()
    cip: CipPolicy = CipPolicy.ENFORCE


# ---------------------------------------------------------------------------
# Applying shocks — pure CALCULATIONS
#
# apply_shocks: (MarketData, ShockSet) → MarketData
# Everything below is a pure function. No mutation, no I/O.
# ---------------------------------------------------------------------------


def apply_shocks(market: MarketData, shocks: ShockSet) -> MarketData:
    """Apply a ShockSet to market data, producing a new snapshot.

    Pure function: (MarketData, ShockSet) → MarketData.

    Order: rate shocks → inflation shocks → FX shocks → CIP adjustment.
    """
    result = market

    # 1. Rate curve shocks
    for shock in shocks.rate_shocks:
        result = _apply_curve_shock(result, shock)

    # 2. Inflation shocks
    for shock in shocks.inflation_shocks:
        result = _apply_inflation_shock(result, shock)

    # 3. FX spot shocks
    for shock in shocks.fx_shocks:
        result = _apply_fx_spot_shock(result, shock)

    # 4. CIP-adjust FX forward curves if policy requires
    if shocks.cip == CipPolicy.ENFORCE:
        result = _enforce_cip(market, result)

    return result


def _apply_curve_shock(market: MarketData, shock: CurveShock) -> MarketData:
    """Apply a single CurveShock to all targeted curves."""
    new_curves = dict(market.discount_curves)

    for key in shock.curves:
        curve = new_curves.get(key)
        if curve is None:
            continue

        bump_fn = _resolve_bump_fn(shock)

        bumped_nodes = tuple(
            CurveNode(
                date=node.date,
                value=_bump_discount_factor(
                    node.value,
                    _years_from_ref(market.valuation_date, node.date),
                    bump_fn,
                ),
            )
            for node in curve.nodes
        )

        new_curves[key] = curve.model_copy(update={"nodes": bumped_nodes})

    return market.model_copy(update={"discount_curves": new_curves})


def _apply_inflation_shock(market: MarketData, shock: InflationShock) -> MarketData:
    """Apply an inflation shock: shift CPI index levels."""
    new_curves = dict(market.inflation_curves)

    for key in shock.curves:
        curve = new_curves.get(key)
        if curve is None:
            continue

        multiplier = 1.0 + shock.level_bps / 10_000
        bumped_nodes = tuple(
            CurveNode(date=n.date, value=n.value * multiplier) for n in curve.nodes
        )
        new_curves[key] = curve.model_copy(update={"nodes": bumped_nodes})

    return market.model_copy(update={"inflation_curves": new_curves})


def _apply_fx_spot_shock(market: MarketData, shock: FxSpotShock) -> MarketData:
    """Apply an FX spot shock."""
    new_spots = dict(market.fx_spot_rates)

    for pair in shock.pairs:
        old_spot = new_spots.get(pair, 0.0)
        if shock.pct != 0.0:
            new_spots[pair] = old_spot * (1.0 + shock.pct / 100.0)
        if shock.absolute != 0.0:
            new_spots[pair] = old_spot + shock.absolute

    return market.model_copy(update={"fx_spot_rates": new_spots})


def _enforce_cip(
    original: MarketData,
    shocked: MarketData,
) -> MarketData:
    """Adjust FX forward curves to maintain covered interest parity.

    CIP: F(t) = S × df_foreign(t) / df_domestic(t)

    For each FX forward curve, recompute forward points from the
    (possibly shocked) discount curves and (possibly shocked) spot.
    """
    new_fx_curves = dict(shocked.fx_curves)

    for key, fx_curve in shocked.fx_curves.items():
        base_ccy = fx_curve.base_currency.value
        quote_ccy = fx_curve.quote_currency.value
        spot_key = f"{base_ccy}/{quote_ccy}"

        spot = shocked.fx_spot_rates.get(spot_key)
        base_dc = shocked.discount_curves.get(base_ccy)
        quote_dc = shocked.discount_curves.get(quote_ccy)

        if spot is None or base_dc is None or quote_dc is None:
            continue

        # Recompute forward points from CIP
        from fi_claude.curves.interpolation import interpolate_discount_factor

        new_nodes = []
        for node in fx_curve.nodes:
            df_base = interpolate_discount_factor(base_dc, node.date)
            df_quote = interpolate_discount_factor(quote_dc, node.date)

            if df_base > 0:
                fwd = spot * df_quote / df_base
                fwd_points = fwd - spot
            else:
                fwd_points = node.value  # fallback: keep original

            new_nodes.append(CurveNode(date=node.date, value=fwd_points))

        new_fx_curves[key] = fx_curve.model_copy(
            update={"nodes": tuple(new_nodes), "spot_rate": spot}
        )

    return shocked.model_copy(update={"fx_curves": new_fx_curves})


# ---------------------------------------------------------------------------
# Shock shape resolution — pure CALCULATION
# ---------------------------------------------------------------------------


def _resolve_bump_fn(shock: CurveShock) -> Callable[[float], float]:
    """Convert a CurveShock spec into a (years) → bps function."""
    if shock.type == ShockType.PARALLEL:
        return lambda y: _parallel(y, bps=shock.bps)

    elif shock.type == ShockType.STEEPEN:
        return lambda y: _steepen(
            y, short_bps=shock.short_bps, long_bps=shock.long_bps,
            short_years=shock.short_years, long_years=shock.long_years,
        )

    elif shock.type == ShockType.FLATTEN:
        # Flatten = inverted steepen
        return lambda y: _steepen(
            y, short_bps=shock.long_bps, long_bps=shock.short_bps,
            short_years=shock.short_years, long_years=shock.long_years,
        )

    elif shock.type == ShockType.TWIST:
        return lambda y: _twist(
            y, pivot_years=shock.pivot_years,
            short_bps=shock.short_bps, long_bps=shock.long_bps,
        )

    elif shock.type == ShockType.POINT:
        return lambda y: _point(
            y, target_years=shock.target_years, bps=shock.bps, width=shock.width,
        )

    elif shock.type == ShockType.CUSTOM:
        return lambda y: _interpolate_custom(y, shock.node_bps)

    msg = f"Unknown shock type: {shock.type}"
    raise ValueError(msg)


def _interpolate_custom(years: float, node_bps: dict[float, float]) -> float:
    """Linearly interpolate custom per-tenor bumps."""
    if not node_bps:
        return 0.0
    tenors = sorted(node_bps.keys())
    if years <= tenors[0]:
        return node_bps[tenors[0]]
    if years >= tenors[-1]:
        return node_bps[tenors[-1]]
    for i in range(len(tenors) - 1):
        if tenors[i] <= years <= tenors[i + 1]:
            t = (years - tenors[i]) / (tenors[i + 1] - tenors[i])
            return node_bps[tenors[i]] + t * (node_bps[tenors[i + 1]] - node_bps[tenors[i]])
    return 0.0


# ---------------------------------------------------------------------------
# Discount factor bump math
# ---------------------------------------------------------------------------


def _bump_discount_factor(df: float, years: float, bump_fn: Callable[[float], float]) -> float:
    """Apply a rate bump (in bps) to a discount factor.

    df = exp(-r * t)  →  df_new = exp(-(r + bump/10000) * t)
                       = df * exp(-bump/10000 * t)
    """
    bump_bps = bump_fn(years)
    return df * math.exp(-bump_bps / 10_000 * years)


def _years_from_ref(ref_date: date, target: date) -> float:
    return (target - ref_date).days / 365.25


# ---------------------------------------------------------------------------
# Convenience constructors — ergonomic one-liners
# ---------------------------------------------------------------------------


def parallel(curves: str | tuple[str, ...], bps: float) -> CurveShock:
    """Parallel rate shock. `parallel("USD", 25)` → +25bps flat."""
    c = (curves,) if isinstance(curves, str) else curves
    return CurveShock(curves=c, type=ShockType.PARALLEL, bps=bps)


def steepen(
    curves: str | tuple[str, ...],
    short_bps: float,
    long_bps: float,
    short_years: float = 0.25,
    long_years: float = 30.0,
) -> CurveShock:
    """Linear steepener. `steepen("USD", -10, 15)` → short end down, long end up."""
    c = (curves,) if isinstance(curves, str) else curves
    return CurveShock(
        curves=c, type=ShockType.STEEPEN,
        short_bps=short_bps, long_bps=long_bps,
        short_years=short_years, long_years=long_years,
    )


def flatten(
    curves: str | tuple[str, ...],
    short_bps: float,
    long_bps: float,
    short_years: float = 0.25,
    long_years: float = 30.0,
) -> CurveShock:
    """Linear flattener (inverted steepener)."""
    c = (curves,) if isinstance(curves, str) else curves
    return CurveShock(
        curves=c, type=ShockType.FLATTEN,
        short_bps=short_bps, long_bps=long_bps,
        short_years=short_years, long_years=long_years,
    )


def twist(
    curves: str | tuple[str, ...],
    pivot_years: float,
    short_bps: float,
    long_bps: float,
) -> CurveShock:
    """Twist around a pivot tenor. `twist("USD", 5.0, -20, 20)` → bear steepener."""
    c = (curves,) if isinstance(curves, str) else curves
    return CurveShock(
        curves=c, type=ShockType.TWIST,
        pivot_years=pivot_years, short_bps=short_bps, long_bps=long_bps,
    )


def point_shock(
    curves: str | tuple[str, ...],
    target_years: float,
    bps: float,
    width: float = 0.5,
) -> CurveShock:
    """Bump concentrated at a single tenor. `point_shock("USD", 5.0, 50)` → 5y +50bps."""
    c = (curves,) if isinstance(curves, str) else curves
    return CurveShock(
        curves=c, type=ShockType.POINT,
        target_years=target_years, bps=bps, width=width,
    )


def custom(curves: str | tuple[str, ...], node_bps: dict[float, float]) -> CurveShock:
    """Arbitrary per-tenor bumps. `custom("USD", {0.25: 5, 2: 10, 10: 25, 30: 30})`."""
    c = (curves,) if isinstance(curves, str) else curves
    return CurveShock(curves=c, type=ShockType.CUSTOM, node_bps=node_bps)


def fx_shock(pairs: str | tuple[str, ...], pct: float = 0.0, absolute: float = 0.0) -> FxSpotShock:
    """FX spot shock. `fx_shock("EUR/USD", pct=-2)` → EUR/USD down 2%."""
    p = (pairs,) if isinstance(pairs, str) else pairs
    return FxSpotShock(pairs=p, pct=pct, absolute=absolute)


def inflation_shock(curves: str | tuple[str, ...], level_bps: float) -> InflationShock:
    """CPI level shock. `inflation_shock("US-CPI", 50)` → CPI +50bps."""
    c = (curves,) if isinstance(curves, str) else curves
    return InflationShock(curves=c, level_bps=level_bps)


def scenario(
    label: str = "",
    *,
    rates: CurveShock | tuple[CurveShock, ...] = (),
    fx: FxSpotShock | tuple[FxSpotShock, ...] = (),
    inflation: InflationShock | tuple[InflationShock, ...] = (),
    cip: CipPolicy = CipPolicy.ENFORCE,
) -> ShockSet:
    """Build a scenario from shocks. The most ergonomic entry point.

    Example:
        s = scenario("Fed +25 / EUR basis",
            rates=(parallel("USD", 25), steepen("EUR", 0, 10)),
            fx=fx_shock("EUR/USD", pct=-1.5),
        )
        shocked = apply_shocks(market, s)
    """
    r = (rates,) if isinstance(rates, CurveShock) else rates
    f = (fx,) if isinstance(fx, FxSpotShock) else fx
    i = (inflation,) if isinstance(inflation, InflationShock) else inflation
    return ShockSet(label=label, rate_shocks=r, fx_shocks=f, inflation_shocks=i, cip=cip)
