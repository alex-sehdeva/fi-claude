"""Market data snapshot — pure DATA.

A MarketData object is an immutable point-in-time snapshot of everything
a pricer needs. Pricers are pure functions: (Instrument, MarketData) → Result.

This is the key architectural decision from Grokking Simplicity:
market data fetch is an ACTION, but once fetched, the snapshot is DATA
that flows through pure CALCULATION functions.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from fi_claude.data.curves import DiscountCurve, FxForwardCurve, InflationCurve


class MarketData(BaseModel, frozen=True):
    """Immutable snapshot of all market data needed for pricing.

    Every pricer takes (Instrument, MarketData) → PricingResult.
    No pricer ever fetches its own data — that would be an ACTION.
    """

    valuation_date: date
    discount_curves: dict[str, DiscountCurve] = {}     # keyed by currency or name
    inflation_curves: dict[str, InflationCurve] = {}    # keyed by index name
    fx_curves: dict[str, FxForwardCurve] = {}           # keyed by "BASE/QUOTE"
    fx_spot_rates: dict[str, float] = {}                # keyed by "BASE/QUOTE"
