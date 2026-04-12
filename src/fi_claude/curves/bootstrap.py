"""Curve bootstrap — pure CALCULATIONS.

Converts observable market rates (DI futures, Treasury yields, swap rates)
into DiscountCurve objects. No I/O — these are pure functions that transform
rate data into the discount factor representation our pricers consume.

Key convention differences handled here:

    BRL-CDI (DI futures):   df = 1 / (1 + r)^(bd/252)
        - Annual compounding under BUS/252
        - Business days drive the exponent, not calendar days
        - r is the DI rate (annualized), bd = business days to maturity

    USD/EUR/MXN (Treasuries, swaps):  df = 1 / (1 + r/n)^(n*t)
        - Semi-annual (n=2) for Treasuries, or continuous: df = exp(-r*t)
        - t in ACT/365.25 year fractions

References:
    - B3 DI-future contract spec: PU = 100,000 / (1+r)^(bd/252)
    - Strata: IsdaCreditCurveDefinition, DiscountFactors
    - QuantLib: PiecewiseYieldCurve bootstrapping
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from fi_claude.data.common import Currency
from fi_claude.data.curves import CurveNode, DiscountCurve, InterpolationMethod


def discount_factor_from_di_rate(rate: float, business_days: int) -> float:
    """Convert a BRL DI futures rate to a discount factor.

    df = 1 / (1 + r)^(bd/252)

    This is the fundamental BRL convention: annual compounding
    over business days with a 252-day year.
    """
    if business_days <= 0:
        return 1.0
    return 1.0 / (1.0 + rate) ** (business_days / 252.0)


def discount_factor_from_yield(
    rate: float,
    years: float,
    compounding: str = "semi-annual",
) -> float:
    """Convert a bond yield to a discount factor.

    Semi-annual (Treasuries):  df = 1 / (1 + r/2)^(2t)
    Annual:                    df = 1 / (1 + r)^t
    Continuous:                df = exp(-r * t)
    """
    if years <= 0:
        return 1.0
    if compounding == "semi-annual":
        return 1.0 / (1.0 + rate / 2.0) ** (2.0 * years)
    elif compounding == "annual":
        return 1.0 / (1.0 + rate) ** years
    elif compounding == "continuous":
        return math.exp(-rate * years)
    msg = f"Unknown compounding: {compounding}"
    raise ValueError(msg)


def build_brl_cdi_curve(
    reference_date: date,
    tenors: dict[str, float],
    *,
    business_day_ratio: float = 252.0 / 365.25,
) -> DiscountCurve:
    """Build a BRL-CDI discount curve from DI futures rates.

    tenors: mapping of tenor label → annualized DI rate.
        Labels: "3M", "6M", "1Y", "2Y", "3Y", "5Y", "10Y" etc.

    Since we don't have an actual holiday calendar, we approximate
    business days as: bd ≈ calendar_days × (252/365.25).
    A production system would use ANBIMA's official calendar.

    Always includes a T=0 node with df=1.0 (the curve starts at par).
    """
    # T=0 anchor: df(today) = 1.0
    nodes = [CurveNode(date=reference_date, value=1.0)]

    for label, rate in sorted(tenors.items(), key=lambda x: _tenor_to_days(x[0])):
        cal_days = _tenor_to_days(label)
        bus_days = round(cal_days * business_day_ratio)
        df = discount_factor_from_di_rate(rate, bus_days)
        node_date = reference_date + timedelta(days=cal_days)
        nodes.append(CurveNode(date=node_date, value=df))

    return DiscountCurve(
        reference_date=reference_date,
        currency=Currency.BRL,
        nodes=tuple(nodes),
        interpolation=InterpolationMethod.LOG_LINEAR,
    )


def build_yield_curve(
    reference_date: date,
    currency: Currency,
    tenors: dict[str, float],
    compounding: str = "semi-annual",
) -> DiscountCurve:
    """Build a discount curve from bond yields or swap rates.

    tenors: mapping of tenor label → annualized yield.
        Labels: "1M", "3M", "6M", "1Y", "2Y", ..., "30Y"

    Always includes a T=0 node with df=1.0.
    """
    # T=0 anchor: df(today) = 1.0
    nodes = [CurveNode(date=reference_date, value=1.0)]

    for label, rate in sorted(tenors.items(), key=lambda x: _tenor_to_days(x[0])):
        cal_days = _tenor_to_days(label)
        years = cal_days / 365.25
        df = discount_factor_from_yield(rate, years, compounding)
        node_date = reference_date + timedelta(days=cal_days)
        nodes.append(CurveNode(date=node_date, value=df))

    return DiscountCurve(
        reference_date=reference_date,
        currency=currency,
        nodes=tuple(nodes),
        interpolation=InterpolationMethod.LOG_LINEAR,
    )


def _tenor_to_days(label: str) -> int:
    """Convert a tenor label like '3M', '1Y', '10Y', '6M' to calendar days."""
    label = label.strip().upper()
    if label.endswith("M"):
        months = int(label[:-1])
        return round(months * 30.4375)  # avg days per month
    elif label.endswith("Y"):
        years = int(label[:-1])
        return round(years * 365.25)
    elif label.endswith("W"):
        weeks = int(label[:-1])
        return weeks * 7
    elif label.endswith("D"):
        return int(label[:-1])
    msg = f"Cannot parse tenor label: {label}"
    raise ValueError(msg)
