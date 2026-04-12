"""Risk sensitivities via finite-difference bumps — pure CALCULATIONS.

The pattern: bump the market data (creating a NEW immutable snapshot),
re-run the pricer, compute the difference. No mutation anywhere.

References:
    - Strata: com.opengamma.strata.measure.* (bump-and-reprice)
    - QuantLib: no built-in bump framework (manual)
"""

from __future__ import annotations

from typing import Callable

from fi_claude.data.market import MarketData
from fi_claude.data.results import PricingResult


def parallel_rate_bump(
    market: MarketData,
    curve_key: str,
    bump_bps: float = 1.0,
) -> MarketData:
    """Create a new MarketData with one curve bumped by bump_bps.

    Pure function: returns a NEW MarketData, original is unchanged.
    """
    curve = market.discount_curves.get(curve_key)
    if curve is None:
        msg = f"No curve '{curve_key}' to bump"
        raise ValueError(msg)

    bump = bump_bps / 10_000
    from fi_claude.data.curves import CurveNode

    bumped_nodes = tuple(
        CurveNode(date=n.date, value=n.value * (1.0 - bump * _approx_years(market, n)))
        for n in curve.nodes
    )

    bumped_curve = curve.model_copy(update={"nodes": bumped_nodes})
    new_curves = {**market.discount_curves, curve_key: bumped_curve}
    return market.model_copy(update={"discount_curves": new_curves})


def dv01(
    pricer: Callable[..., PricingResult],
    pricer_args: tuple,
    market: MarketData,
    curve_key: str,
    bump_bps: float = 1.0,
) -> float:
    """Compute DV01: PV change for a 1bp parallel rate bump.

    Pure function: runs pricer twice (base + bumped), returns difference.
    """
    base_result = pricer(*pricer_args, market)
    bumped_market = parallel_rate_bump(market, curve_key, bump_bps)
    bumped_args = (*pricer_args[:-1],) if pricer_args else ()  # replace market arg
    bumped_result = pricer(*bumped_args, bumped_market) if bumped_args else pricer(bumped_market)

    return float(bumped_result.present_value - base_result.present_value)


def _approx_years(market: MarketData, node: object) -> float:
    """Approximate years from valuation date to node date."""
    from fi_claude.data.curves import CurveNode

    if isinstance(node, CurveNode):
        return (node.date - market.valuation_date).days / 365.25
    return 0.0
