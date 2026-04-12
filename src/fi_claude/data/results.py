"""Pricing results — pure DATA returned by pricers.

Grokking Simplicity: pricers are CALCULATIONS that return DATA.
Results are frozen and composable.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from fi_claude.data.common import Cashflow, Currency


class PricingResult(BaseModel, frozen=True):
    """The output of any pricer."""

    instrument_type: str
    valuation_date: date
    currency: Currency
    present_value: Decimal
    cashflows: tuple[Cashflow, ...] = ()
    details: dict[str, float] = {}   # pricer-specific metrics (dv01, accrued, etc.)
