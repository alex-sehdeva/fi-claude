"""Cashflow report — pure CALCULATION.

Builds a rich cashflow report from a PricingResult, computing
WAL, totals, and rendering a human-readable ASCII table.

Grokking Simplicity: CALCULATION layer — same inputs, same outputs.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from fi_claude.data.common import Cashflow
from fi_claude.data.results import PricingResult


class CashflowReport(BaseModel, frozen=True):
    """A full cashflow report for client inspection."""

    instrument_type: str
    currency: str
    valuation_date: date
    cashflows: tuple[Cashflow, ...]
    total_pv: Decimal
    total_undiscounted: Decimal
    weighted_average_life: float


def build_cashflow_report(
    result: PricingResult,
    valuation_date: date,
) -> CashflowReport:
    """Build a CashflowReport from a PricingResult.

    Pure function: (PricingResult, date) -> CashflowReport.

    WAL = sum(t_i * amount_i) / sum(amount_i) where t_i is years from
    valuation_date to payment_date, considering only future cashflows
    with positive amounts.
    """
    future_cfs = tuple(
        cf for cf in result.cashflows if cf.payment_date > valuation_date
    )

    total_undiscounted = sum(
        (cf.amount for cf in future_cfs), Decimal("0")
    )

    total_pv = sum(
        (cf.present_value for cf in future_cfs if cf.present_value is not None),
        Decimal("0"),
    )

    # WAL: weighted by undiscounted amounts of positive cashflows
    wal_numerator = 0.0
    wal_denominator = 0.0
    for cf in future_cfs:
        amt = float(cf.amount)
        if amt > 0:
            years = (cf.payment_date - valuation_date).days / 365.25
            wal_numerator += years * amt
            wal_denominator += amt

    wal = wal_numerator / wal_denominator if wal_denominator > 0 else 0.0

    return CashflowReport(
        instrument_type=result.instrument_type,
        currency=result.currency.value,
        valuation_date=valuation_date,
        cashflows=future_cfs,
        total_pv=total_pv,
        total_undiscounted=total_undiscounted,
        weighted_average_life=round(wal, 4),
    )


def format_cashflow_table(report: CashflowReport) -> str:
    """Render a human-readable ASCII table of cashflows.

    Pure function: CashflowReport -> str.

    Columns: Date | Type | Label | Amount | DF | PV | Cumulative PV
    """
    header = (
        f"{'Date':<12} {'Type':<20} {'Label':<24} "
        f"{'Amount':>14} {'DF':>8} {'PV':>14} {'Cumulative PV':>14}"
    )
    sep = "-" * len(header)

    lines: list[str] = []
    lines.append(f"Cashflow Report: {report.instrument_type} ({report.currency})")
    lines.append(f"Valuation Date: {report.valuation_date}")
    lines.append(f"WAL: {report.weighted_average_life:.4f} years")
    lines.append(sep)
    lines.append(header)
    lines.append(sep)

    cumulative_pv = Decimal("0")
    for cf in report.cashflows:
        pv = cf.present_value if cf.present_value is not None else Decimal("0")
        cumulative_pv += pv
        df_str = f"{cf.discount_factor:.6f}" if cf.discount_factor is not None else ""
        pv_str = f"{pv:>14.2f}"
        lines.append(
            f"{str(cf.payment_date):<12} {cf.cashflow_type.value:<20} {cf.label:<24} "
            f"{cf.amount:>14.2f} {df_str:>8} {pv_str} {cumulative_pv:>14.2f}"
        )

    lines.append(sep)
    lines.append(
        f"{'Total':<12} {'':<20} {'':<24} "
        f"{report.total_undiscounted:>14.2f} {'':<8} {report.total_pv:>14.2f}"
    )

    return "\n".join(lines)
