"""Day-count fraction calculations — pure CALCULATIONS.

References:
    - Strata: com.opengamma.strata.basics.date.DayCounts
    - QuantLib: ql/time/daycounters/
    - ISDA 2006 definitions
"""

from __future__ import annotations

from datetime import date

from fi_claude.data.common import DayCountConvention


def year_fraction(
    start: date,
    end: date,
    convention: DayCountConvention,
    business_days: int | None = None,
) -> float:
    """Calculate the year fraction between two dates.

    Pure function: (date, date, convention) → float.

    For BUS/252 convention, business_days must be provided
    (computing it requires a holiday calendar — that's a separate concern).
    """
    if start >= end:
        return 0.0

    if convention == DayCountConvention.ACT_360:
        return (end - start).days / 360.0

    elif convention == DayCountConvention.ACT_365:
        return (end - start).days / 365.0

    elif convention == DayCountConvention.ACT_ACT:
        return (end - start).days / _days_in_year(start, end)

    elif convention == DayCountConvention.THIRTY_360:
        return _thirty_360(start, end)

    elif convention == DayCountConvention.BUS_252:
        if business_days is None:
            msg = "BUS/252 requires business_days count (depends on holiday calendar)"
            raise ValueError(msg)
        return business_days / 252.0

    msg = f"Unknown day count convention: {convention}"
    raise ValueError(msg)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _days_in_year(start: date, end: date) -> float:
    """Approximate days-in-year for ACT/ACT."""
    years = end.year - start.year
    if years == 0:
        year_start = date(start.year, 1, 1)
        year_end = date(start.year + 1, 1, 1)
        return float((year_end - year_start).days)
    total_days = (date(end.year + 1, 1, 1) - date(start.year, 1, 1)).days
    return total_days / (years + 1)


def _thirty_360(start: date, end: date) -> float:
    """30/360 Bond Basis (ISDA)."""
    d1 = min(start.day, 30)
    d2 = min(end.day, 30) if d1 == 30 else end.day
    return (360 * (end.year - start.year) + 30 * (end.month - start.month) + (d2 - d1)) / 360.0
