"""Shared test fixtures — pure DATA factories.

Every fixture returns immutable data. No I/O, no mocks.
This is what Grokking Simplicity means by "calculations are easy to test."
"""

from datetime import date
from decimal import Decimal

import pytest

from fi_claude.data.common import Currency, DayCountConvention, PayReceive
from fi_claude.data.curves import CurveNode, DiscountCurve, InflationCurve, InterpolationMethod
from fi_claude.data.instruments import (
    AgencyProgram,
    BrlPreCdiSwap,
    CouponScheduleEntry,
    InflationLagConvention,
    InflationLinkedBond,
    TbaContract,
    XccyBasisSwap,
    XccyLeg,
)
from fi_claude.data.market import MarketData


@pytest.fixture
def valuation_date() -> date:
    return date(2025, 6, 15)


@pytest.fixture
def brl_cdi_curve(valuation_date: date) -> DiscountCurve:
    """A simple BRL CDI discount curve."""
    return DiscountCurve(
        reference_date=valuation_date,
        currency=Currency.BRL,
        nodes=(
            CurveNode(date=date(2025, 7, 15), value=0.9890),
            CurveNode(date=date(2025, 12, 15), value=0.9400),
            CurveNode(date=date(2026, 6, 15), value=0.8800),
            CurveNode(date=date(2027, 6, 15), value=0.7700),
        ),
        interpolation=InterpolationMethod.LOG_LINEAR,
    )


@pytest.fixture
def usd_curve(valuation_date: date) -> DiscountCurve:
    return DiscountCurve(
        reference_date=valuation_date,
        currency=Currency.USD,
        nodes=(
            CurveNode(date=date(2025, 7, 15), value=0.9960),
            CurveNode(date=date(2025, 12, 15), value=0.9780),
            CurveNode(date=date(2026, 6, 15), value=0.9550),
            CurveNode(date=date(2027, 6, 15), value=0.9100),
        ),
        interpolation=InterpolationMethod.LOG_LINEAR,
    )


@pytest.fixture
def eur_curve(valuation_date: date) -> DiscountCurve:
    return DiscountCurve(
        reference_date=valuation_date,
        currency=Currency.EUR,
        nodes=(
            CurveNode(date=date(2025, 7, 15), value=0.9975),
            CurveNode(date=date(2025, 12, 15), value=0.9850),
            CurveNode(date=date(2026, 6, 15), value=0.9680),
            CurveNode(date=date(2027, 6, 15), value=0.9350),
        ),
        interpolation=InterpolationMethod.LOG_LINEAR,
    )


@pytest.fixture
def us_cpi_curve(valuation_date: date) -> InflationCurve:
    return InflationCurve(
        reference_date=valuation_date,
        base_index_level=310.0,
        nodes=(
            CurveNode(date=date(2025, 7, 15), value=311.5),
            CurveNode(date=date(2025, 12, 15), value=314.0),
            CurveNode(date=date(2026, 6, 15), value=317.0),
            CurveNode(date=date(2027, 6, 15), value=323.0),
        ),
    )


@pytest.fixture
def sample_brl_swap() -> BrlPreCdiSwap:
    return BrlPreCdiSwap(
        notional=Decimal("10000000"),
        fixed_rate=0.1350,
        start_date=date(2025, 6, 15),
        end_date=date(2026, 6, 15),
        pay_receive_fixed=PayReceive.PAY,
    )


@pytest.fixture
def sample_tips_bond() -> InflationLinkedBond:
    return InflationLinkedBond(
        face_value=Decimal("1000000"),
        real_coupon_rate=0.0125,
        issue_date=date(2024, 1, 15),
        maturity_date=date(2027, 1, 15),
        currency=Currency.USD,
        day_count=DayCountConvention.ACT_ACT,
        base_cpi=305.0,
        inflation_lag=InflationLagConvention.THREE_MONTHS,
        coupon_schedule=(
            CouponScheduleEntry(
                accrual_start=date(2025, 1, 15),
                accrual_end=date(2025, 7, 15),
                payment_date=date(2025, 7, 15),
            ),
            CouponScheduleEntry(
                accrual_start=date(2025, 7, 15),
                accrual_end=date(2026, 1, 15),
                payment_date=date(2026, 1, 15),
            ),
            CouponScheduleEntry(
                accrual_start=date(2026, 1, 15),
                accrual_end=date(2026, 7, 15),
                payment_date=date(2026, 7, 15),
            ),
            CouponScheduleEntry(
                accrual_start=date(2026, 7, 15),
                accrual_end=date(2027, 1, 15),
                payment_date=date(2027, 1, 15),
            ),
        ),
    )


@pytest.fixture
def sample_xccy_swap() -> XccyBasisSwap:
    return XccyBasisSwap(
        near_leg=XccyLeg(
            currency=Currency.USD,
            notional=Decimal("10000000"),
            floating_index="SOFR",
            spread_bps=0.0,
        ),
        far_leg=XccyLeg(
            currency=Currency.EUR,
            notional=Decimal("9200000"),
            floating_index="EURIBOR_3M",
            spread_bps=-15.0,
        ),
        start_date=date(2025, 6, 15),
        end_date=date(2027, 6, 15),
        fx_rate_at_inception=1.087,
    )


@pytest.fixture
def sample_tba() -> TbaContract:
    return TbaContract(
        agency=AgencyProgram.FNMA,
        coupon_rate=0.055,
        original_term_years=30,
        face_value=Decimal("1000000"),
        settlement_date=date(2025, 7, 15),
        assumed_cpr=0.08,
    )


@pytest.fixture
def market_data(
    valuation_date: date,
    brl_cdi_curve: DiscountCurve,
    usd_curve: DiscountCurve,
    eur_curve: DiscountCurve,
    us_cpi_curve: InflationCurve,
) -> MarketData:
    return MarketData(
        valuation_date=valuation_date,
        discount_curves={
            "BRL-CDI": brl_cdi_curve,
            "USD": usd_curve,
            "USD-REAL": usd_curve,  # reuse as real curve for simplicity
            "EUR": eur_curve,
        },
        inflation_curves={"US-CPI": us_cpi_curve},
        fx_spot_rates={"EUR/USD": 1.087},
    )
