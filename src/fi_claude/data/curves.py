"""Curve data models — pure DATA, no interpolation logic.

A curve is a snapshot of market state: a sorted list of (date, value) pairs.
Interpolation is a CALCULATION (Layer 1) that takes a curve as input.

References:
    - Strata: com.opengamma.strata.market.curve.InterpolatedNodalCurve
    - QuantLib: ql/termstructures/yieldtermstructure.hpp
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, field_validator

from fi_claude.data.common import Currency


class InterpolationMethod(str, Enum):
    LINEAR = "LINEAR"
    LOG_LINEAR = "LOG_LINEAR"
    CUBIC_SPLINE = "CUBIC_SPLINE"
    FLAT_FORWARD = "FLAT_FORWARD"


class CurveNode(BaseModel, frozen=True):
    """A single point on a curve."""

    date: date
    value: float


class DiscountCurve(BaseModel, frozen=True):
    """An immutable snapshot of a discount curve.

    Nodes are sorted by date. The curve itself is pure data —
    interpolation is a separate calculation function.
    """

    reference_date: date
    currency: Currency
    nodes: tuple[CurveNode, ...]
    interpolation: InterpolationMethod = InterpolationMethod.LOG_LINEAR

    @field_validator("nodes")
    @classmethod
    def _sorted_by_date(cls, v: tuple[CurveNode, ...]) -> tuple[CurveNode, ...]:
        dates = [n.date for n in v]
        if dates != sorted(dates):
            msg = "Curve nodes must be sorted by date"
            raise ValueError(msg)
        return v


class InflationCurve(BaseModel, frozen=True):
    """CPI index-level curve for inflation-linked pricing.

    Each node maps a date to a CPI index level (e.g., 312.5).

    References:
        - Strata: com.opengamma.strata.pricer.bond.DiscountingCapitalIndexedBondProductPricer
        - QuantLib: ql/termstructures/inflation/inflationtermstructure.hpp
    """

    reference_date: date
    base_index_level: float
    nodes: tuple[CurveNode, ...]
    interpolation: InterpolationMethod = InterpolationMethod.LINEAR

    @field_validator("nodes")
    @classmethod
    def _sorted_by_date(cls, v: tuple[CurveNode, ...]) -> tuple[CurveNode, ...]:
        dates = [n.date for n in v]
        if dates != sorted(dates):
            msg = "Inflation curve nodes must be sorted by date"
            raise ValueError(msg)
        return v


class FxForwardCurve(BaseModel, frozen=True):
    """FX forward points for cross-currency pricing."""

    reference_date: date
    base_currency: Currency
    quote_currency: Currency
    spot_rate: float
    nodes: tuple[CurveNode, ...]  # forward points (delta from spot)
    interpolation: InterpolationMethod = InterpolationMethod.LINEAR
