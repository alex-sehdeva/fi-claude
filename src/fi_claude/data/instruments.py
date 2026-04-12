"""Instrument definitions — pure DATA describing trade terms.

Each instrument is a frozen Pydantic model that captures the contractual
terms of a trade. No pricing logic, no market data references, no state.

Grokking Simplicity: these are DATA.

References:
    - Strata products: com.opengamma.strata.product.*
    - QuantLib instruments: ql/instruments/
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel

from fi_claude.data.common import (
    BusinessDayConvention,
    CompoundingMethod,
    Currency,
    DayCountConvention,
    PayReceive,
)


# ---------------------------------------------------------------------------
# BRL Pre-CDI Swap
# ---------------------------------------------------------------------------
# A Pre-CDI swap exchanges:
#   - Fixed leg: pre-fixed rate, BUS/252 day count, BRL
#   - Float leg: CDI overnight rate compounded daily, BUS/252 day count, BRL
#
# Neither Strata nor QuantLib has a turnkey Pre-CDI. Strata has a BRL-CDI
# index; QuantLib-Ext has BRLCdiSwap. We model from first principles.


class BrlPreCdiSwap(BaseModel, frozen=True):
    """BRL Pre x CDI interest rate swap."""

    notional: Decimal
    fixed_rate: float                  # annualized, e.g. 0.1350 for 13.50%
    start_date: date
    end_date: date
    pay_receive_fixed: PayReceive      # PAY fixed = receive CDI
    day_count: DayCountConvention = DayCountConvention.BUS_252
    compounding: CompoundingMethod = CompoundingMethod.OVERNIGHT_COMPOUNDED
    currency: Currency = Currency.BRL


# ---------------------------------------------------------------------------
# Inflation-Linked Bond
# ---------------------------------------------------------------------------
# Both Strata (CapitalIndexedBond) and QuantLib (CPIBond) support this.
# We model the generic case covering US TIPS, BR NTN-B, UK linkers, etc.


class InflationLagConvention(str, Enum):
    """How the CPI reference is lagged."""

    THREE_MONTHS = "3M"     # US TIPS, UK linkers
    TWO_MONTHS = "2M"       # some eurozone
    NO_LAG = "0M"           # theoretical


class CouponScheduleEntry(BaseModel, frozen=True):
    """One coupon period."""

    accrual_start: date
    accrual_end: date
    payment_date: date


class InflationLinkedBond(BaseModel, frozen=True):
    """A bond whose principal and/or coupons are indexed to inflation.

    References:
        - Strata: CapitalIndexedBond, InflationRateCalculation
        - QuantLib: CPIBond, ZeroCouponInflationSwap
    """

    face_value: Decimal
    real_coupon_rate: float             # real (not nominal) coupon rate
    issue_date: date
    maturity_date: date
    currency: Currency
    day_count: DayCountConvention
    base_cpi: float                     # CPI level at issue
    inflation_lag: InflationLagConvention = InflationLagConvention.THREE_MONTHS
    coupon_frequency_months: int = 6    # typically semi-annual
    deflation_floor: bool = True        # principal protected at par?
    coupon_schedule: tuple[CouponScheduleEntry, ...] = ()


# ---------------------------------------------------------------------------
# Cross-Currency Basis Swap
# ---------------------------------------------------------------------------
# Strata supports this as first-class. QuantLib has curve helpers but no
# turnkey pricer (see issue #2201). We model both MtM and non-MtM variants.


class XccyLeg(BaseModel, frozen=True):
    """One leg of a cross-currency basis swap."""

    currency: Currency
    notional: Decimal
    floating_index: str                # e.g. "SOFR", "EURIBOR_3M", "CDI"
    spread_bps: float = 0.0           # basis spread in bps
    day_count: DayCountConvention = DayCountConvention.ACT_360
    compounding: CompoundingMethod = CompoundingMethod.COMPOUNDED
    payment_frequency_months: int = 3


class XccyBasisSwap(BaseModel, frozen=True):
    """Cross-currency basis swap.

    Two floating legs in different currencies, typically with
    initial and final notional exchanges.

    References:
        - Strata: Swap with cross-currency legs, FxReset
        - QuantLib: CrossCurrencyBasisSwapRateHelper (curve only)
    """

    near_leg: XccyLeg
    far_leg: XccyLeg
    start_date: date
    end_date: date
    initial_exchange: bool = True
    final_exchange: bool = True
    mark_to_market_reset: bool = True  # MtM notional resets on near leg
    fx_rate_at_inception: float | None = None


# ---------------------------------------------------------------------------
# TBA (To-Be-Announced)
# ---------------------------------------------------------------------------
# Neither Strata nor QuantLib supports TBAs.
# TBAs are forward contracts on agency MBS pools.
# Pricing requires prepayment models — a genuinely greenfield build.


class AgencyProgram(str, Enum):
    FNMA = "FNMA"       # Fannie Mae
    FHLMC = "FHLMC"     # Freddie Mac
    GNMA = "GNMA"       # Ginnie Mae


class TbaContract(BaseModel, frozen=True):
    """To-Be-Announced mortgage-backed security forward contract.

    TBAs are standardized by: agency, coupon, maturity, settlement month.
    The actual pool is not known until 48 hours before settlement.

    No existing open-source library prices these.
    Requires prepayment model + pool aggregation.
    """

    agency: AgencyProgram
    coupon_rate: float                  # e.g. 0.055 for 5.5%
    original_term_years: int            # 15 or 30
    face_value: Decimal
    settlement_date: date
    currency: Currency = Currency.USD
    pool_factor: float = 1.0           # remaining principal fraction
    assumed_cpr: float | None = None   # constant prepayment rate for pricing
    assumed_cdr: float | None = None   # constant default rate
    loss_severity: float | None = None
