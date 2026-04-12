"""TBA (To-Be-Announced) pricer — pure CALCULATION.

TBAs are forward contracts on agency MBS pools. Pricing requires
a prepayment model to project cashflows, then discounting.

Neither Strata nor QuantLib supports TBAs. This is greenfield.

References:
    - SIFMA TBA trading conventions
    - PSA (Public Securities Association) prepayment model
    - Bloomberg methodology: TBA pricing and risk
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fi_claude.curves.interpolation import interpolate_discount_factor
from fi_claude.data.common import Cashflow, Currency
from fi_claude.data.instruments import TbaContract
from fi_claude.data.market import MarketData
from fi_claude.data.results import PricingResult


def price_tba(
    tba: TbaContract,
    market: MarketData,
) -> PricingResult:
    """Price a TBA contract.

    Pure function: (TbaContract, MarketData) → PricingResult.

    Uses a simplified constant-prepayment-rate (CPR) model to project
    cashflows, then discounts them on the USD curve.
    """
    curve = market.discount_curves.get("USD")
    if curve is None:
        msg = "MarketData missing 'USD' discount curve"
        raise ValueError(msg)

    valuation = market.valuation_date
    cpr = tba.assumed_cpr if tba.assumed_cpr is not None else 0.06  # 6% CPR default

    # Generate projected cashflows under CPR model
    projected = _project_cashflows_cpr(
        face=float(tba.face_value),
        coupon_rate=tba.coupon_rate,
        term_months=tba.original_term_years * 12,
        settlement=tba.settlement_date,
        pool_factor=tba.pool_factor,
        cpr=cpr,
    )

    # Discount each cashflow
    total_pv = 0.0
    result_cashflows: list[Cashflow] = []

    for cf_date, cf_amount in projected:
        if cf_date <= valuation:
            continue
        df = interpolate_discount_factor(curve, cf_date)
        total_pv += cf_amount * df
        result_cashflows.append(Cashflow(
            payment_date=cf_date,
            amount=Decimal(str(round(cf_amount, 2))),
            currency=Currency.USD,
        ))

    return PricingResult(
        instrument_type="TBA",
        valuation_date=valuation,
        currency=Currency.USD,
        present_value=Decimal(str(round(total_pv, 2))),
        cashflows=tuple(result_cashflows),
        details={
            "assumed_cpr": cpr,
            "pool_factor": tba.pool_factor,
            "projected_cashflow_count": float(len(projected)),
        },
    )


# ---------------------------------------------------------------------------
# Prepayment model — pure CALCULATIONS
# ---------------------------------------------------------------------------


def _project_cashflows_cpr(
    face: float,
    coupon_rate: float,
    term_months: int,
    settlement: date,
    pool_factor: float,
    cpr: float,
) -> list[tuple[date, float]]:
    """Project mortgage cashflows under a constant prepayment rate.

    PSA model: SMM (single monthly mortality) = 1 - (1 - CPR)^(1/12)

    Returns a list of (date, total_cashflow) pairs.
    """
    from dateutil.relativedelta import relativedelta  # type: ignore[import-untyped]

    smm = 1.0 - (1.0 - cpr) ** (1.0 / 12.0)
    monthly_rate = coupon_rate / 12.0
    remaining_balance = face * pool_factor
    cashflows: list[tuple[date, float]] = []

    for month in range(1, term_months + 1):
        if remaining_balance < 0.01:
            break

        cf_date = settlement + relativedelta(months=month)

        # Scheduled payment (level-pay amortization)
        remaining_term = term_months - month + 1
        if monthly_rate > 0 and remaining_term > 0:
            scheduled_payment = remaining_balance * (
                monthly_rate / (1.0 - (1.0 + monthly_rate) ** (-remaining_term))
            )
        else:
            scheduled_payment = remaining_balance / max(remaining_term, 1)

        # Interest and principal components
        interest = remaining_balance * monthly_rate
        scheduled_principal = scheduled_payment - interest

        # Prepayment
        prepayment = (remaining_balance - scheduled_principal) * smm

        total_principal = scheduled_principal + prepayment
        total_cashflow = interest + total_principal

        cashflows.append((cf_date, total_cashflow))
        remaining_balance -= total_principal

    return cashflows
