"""Common data types shared across all instruments.

These are pure DATA in Grokking Simplicity terms — frozen, immutable,
no side effects. They describe *what things are*, not what to do with them.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class Currency(str, Enum):
    """ISO 4217 currency codes we care about."""

    BRL = "BRL"
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"


class DayCountConvention(str, Enum):
    """Day-count conventions.

    References:
        - Strata: com.opengamma.strata.basics.date.DayCounts
        - QuantLib: ql/time/daycounters/
    """

    ACT_360 = "ACT/360"
    ACT_365 = "ACT/365"
    ACT_ACT = "ACT/ACT"
    THIRTY_360 = "30/360"
    BUS_252 = "BUS/252"  # Brazilian business-day convention


class BusinessDayConvention(str, Enum):
    FOLLOWING = "FOLLOWING"
    MODIFIED_FOLLOWING = "MODIFIED_FOLLOWING"
    PRECEDING = "PRECEDING"


class CompoundingMethod(str, Enum):
    """How rates compound within a period."""

    SIMPLE = "SIMPLE"
    COMPOUNDED = "COMPOUNDED"          # standard discrete compounding
    CONTINUOUS = "CONTINUOUS"
    OVERNIGHT_COMPOUNDED = "OVERNIGHT_COMPOUNDED"  # CDI-style daily compounding


class PayReceive(str, Enum):
    PAY = "PAY"
    RECEIVE = "RECEIVE"


# ---------------------------------------------------------------------------
# Core value types
# ---------------------------------------------------------------------------


class Cashflow(BaseModel, frozen=True):
    """A single dated cashflow — the atomic unit of fixed income."""

    payment_date: date
    amount: Decimal
    currency: Currency


class DiscountFactor(BaseModel, frozen=True):
    """A point on a discount curve: date → factor."""

    date: date
    factor: float


class RateQuote(BaseModel, frozen=True):
    """An observed market rate at a point in time."""

    date: date
    tenor_days: int
    rate: float
    currency: Currency
