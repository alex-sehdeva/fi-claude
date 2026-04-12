"""Curve interpolation — pure CALCULATIONS.

Each function takes immutable curve data and returns a value.
No state, no mutation.

If QuantLib is installed, we can delegate to its battle-tested
interpolation. But the interface is ours — QuantLib is an
implementation detail, not an architectural dependency.

References:
    - Strata: com.opengamma.strata.market.curve.interpolator.*
    - QuantLib: ql/math/interpolations/
"""

from __future__ import annotations

import math
from datetime import date

from fi_claude.data.curves import CurveNode, DiscountCurve, InterpolationMethod


def interpolate_discount_factor(curve: DiscountCurve, target: date) -> float:
    """Interpolate a discount factor for a given date.

    Pure function: (DiscountCurve, date) → float.
    """
    if not curve.nodes:
        msg = "Cannot interpolate empty curve"
        raise ValueError(msg)

    nodes = curve.nodes
    ref = curve.reference_date

    # Exact match
    for node in nodes:
        if node.date == target:
            return node.value

    # Before first node: flat extrapolation
    if target <= nodes[0].date:
        return nodes[0].value

    # After last node: flat extrapolation
    if target >= nodes[-1].date:
        return nodes[-1].value

    # Find bracketing nodes
    left, right = _find_bracket(nodes, target)

    # Interpolate based on method
    t = _year_fraction(ref, target, left.date, right.date)

    if curve.interpolation == InterpolationMethod.LINEAR:
        return _linear(left.value, right.value, t)
    elif curve.interpolation == InterpolationMethod.LOG_LINEAR:
        return _log_linear(left.value, right.value, t)
    else:
        return _linear(left.value, right.value, t)


# ---------------------------------------------------------------------------
# Pure helper calculations
# ---------------------------------------------------------------------------


def _find_bracket(
    nodes: tuple[CurveNode, ...], target: date
) -> tuple[CurveNode, CurveNode]:
    """Find the two nodes that bracket the target date."""
    for i in range(len(nodes) - 1):
        if nodes[i].date <= target <= nodes[i + 1].date:
            return nodes[i], nodes[i + 1]
    msg = f"Target {target} not bracketed by curve nodes"
    raise ValueError(msg)


def _year_fraction(
    ref: date, target: date, left_date: date, right_date: date
) -> float:
    """Fraction of the interval [left, right] at which target falls."""
    total = (right_date - left_date).days
    if total == 0:
        return 0.0
    elapsed = (target - left_date).days
    return elapsed / total


def _linear(left: float, right: float, t: float) -> float:
    return left + t * (right - left)


def _log_linear(left: float, right: float, t: float) -> float:
    if left <= 0 or right <= 0:
        return _linear(left, right, t)
    return math.exp(math.log(left) + t * (math.log(right) - math.log(left)))
