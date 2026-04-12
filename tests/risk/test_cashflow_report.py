"""Test cashflow report — build_cashflow_report, format_cashflow_table, pricer enrichment."""

from datetime import date
from decimal import Decimal

import pytest

from fi_claude.data.common import Cashflow, CashflowType, Currency
from fi_claude.data.instruments import InflationLinkedBond, TbaContract
from fi_claude.data.market import MarketData
from fi_claude.data.results import PricingResult
from fi_claude.pricers.inflation_bond import price_inflation_linked_bond
from fi_claude.pricers.tba import price_tba
from fi_claude.pricers.xccy_basis_swap import price_xccy_basis_swap
from fi_claude.risk.cashflow_report import (
    CashflowReport,
    build_cashflow_report,
    format_cashflow_table,
)


# ---------------------------------------------------------------------------
# build_cashflow_report
# ---------------------------------------------------------------------------


class TestBuildCashflowReport:
    def test_wal_simple(self):
        """WAL with two equal cashflows at 1 and 2 years should be 1.5 years."""
        val = date(2025, 1, 1)
        cfs = (
            Cashflow(
                payment_date=date(2026, 1, 1),
                amount=Decimal("100"),
                currency=Currency.USD,
                cashflow_type=CashflowType.PRINCIPAL,
                present_value=Decimal("95"),
                discount_factor=0.95,
            ),
            Cashflow(
                payment_date=date(2027, 1, 1),
                amount=Decimal("100"),
                currency=Currency.USD,
                cashflow_type=CashflowType.PRINCIPAL,
                present_value=Decimal("90"),
                discount_factor=0.90,
            ),
        )
        result = PricingResult(
            instrument_type="TEST",
            valuation_date=val,
            currency=Currency.USD,
            present_value=Decimal("185"),
            cashflows=cfs,
        )
        report = build_cashflow_report(result, val)

        # WAL should be approximately 1.5 years
        assert 1.49 < report.weighted_average_life < 1.51

    def test_total_undiscounted(self):
        val = date(2025, 1, 1)
        cfs = (
            Cashflow(
                payment_date=date(2025, 7, 1),
                amount=Decimal("300"),
                currency=Currency.USD,
                present_value=Decimal("290"),
            ),
            Cashflow(
                payment_date=date(2026, 1, 1),
                amount=Decimal("700"),
                currency=Currency.USD,
                present_value=Decimal("650"),
            ),
        )
        result = PricingResult(
            instrument_type="TEST",
            valuation_date=val,
            currency=Currency.USD,
            present_value=Decimal("940"),
            cashflows=cfs,
        )
        report = build_cashflow_report(result, val)
        assert report.total_undiscounted == Decimal("1000")

    def test_total_pv(self):
        val = date(2025, 1, 1)
        cfs = (
            Cashflow(
                payment_date=date(2025, 7, 1),
                amount=Decimal("300"),
                currency=Currency.USD,
                present_value=Decimal("290"),
            ),
            Cashflow(
                payment_date=date(2026, 1, 1),
                amount=Decimal("700"),
                currency=Currency.USD,
                present_value=Decimal("650"),
            ),
        )
        result = PricingResult(
            instrument_type="TEST",
            valuation_date=val,
            currency=Currency.USD,
            present_value=Decimal("940"),
            cashflows=cfs,
        )
        report = build_cashflow_report(result, val)
        assert report.total_pv == Decimal("940")

    def test_excludes_past_cashflows(self):
        val = date(2025, 6, 15)
        cfs = (
            Cashflow(
                payment_date=date(2025, 1, 1),
                amount=Decimal("500"),
                currency=Currency.USD,
            ),
            Cashflow(
                payment_date=date(2025, 12, 1),
                amount=Decimal("500"),
                currency=Currency.USD,
                present_value=Decimal("480"),
            ),
        )
        result = PricingResult(
            instrument_type="TEST",
            valuation_date=val,
            currency=Currency.USD,
            present_value=Decimal("480"),
            cashflows=cfs,
        )
        report = build_cashflow_report(result, val)
        assert len(report.cashflows) == 1
        assert report.total_undiscounted == Decimal("500")

    def test_empty_cashflows(self):
        val = date(2025, 1, 1)
        result = PricingResult(
            instrument_type="TEST",
            valuation_date=val,
            currency=Currency.USD,
            present_value=Decimal("0"),
        )
        report = build_cashflow_report(result, val)
        assert report.weighted_average_life == 0.0
        assert report.total_undiscounted == Decimal("0")

    def test_report_frozen(self):
        val = date(2025, 1, 1)
        result = PricingResult(
            instrument_type="TEST",
            valuation_date=val,
            currency=Currency.USD,
            present_value=Decimal("0"),
        )
        report = build_cashflow_report(result, val)
        with pytest.raises(Exception):
            report.weighted_average_life = 999.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# format_cashflow_table
# ---------------------------------------------------------------------------


class TestFormatCashflowTable:
    def test_has_column_headers(self):
        val = date(2025, 1, 1)
        cfs = (
            Cashflow(
                payment_date=date(2025, 7, 1),
                amount=Decimal("100"),
                currency=Currency.USD,
                cashflow_type=CashflowType.COUPON,
                label="coupon",
                discount_factor=0.98,
                present_value=Decimal("98"),
            ),
        )
        report = CashflowReport(
            instrument_type="TEST",
            currency="USD",
            valuation_date=val,
            cashflows=cfs,
            total_pv=Decimal("98"),
            total_undiscounted=Decimal("100"),
            weighted_average_life=0.5,
        )
        table = format_cashflow_table(report)

        assert "Date" in table
        assert "Type" in table
        assert "Label" in table
        assert "Amount" in table
        assert "DF" in table
        assert "PV" in table
        assert "Cumulative PV" in table

    def test_contains_cashflow_data(self):
        val = date(2025, 1, 1)
        cfs = (
            Cashflow(
                payment_date=date(2025, 7, 1),
                amount=Decimal("1000.50"),
                currency=Currency.USD,
                cashflow_type=CashflowType.PRINCIPAL,
                label="principal at maturity",
                discount_factor=0.97,
                present_value=Decimal("970.49"),
            ),
        )
        report = CashflowReport(
            instrument_type="BOND",
            currency="USD",
            valuation_date=val,
            cashflows=cfs,
            total_pv=Decimal("970.49"),
            total_undiscounted=Decimal("1000.50"),
            weighted_average_life=0.5,
        )
        table = format_cashflow_table(report)

        assert "2025-07-01" in table
        assert "PRINCIPAL" in table
        assert "principal at maturity" in table
        assert "BOND" in table

    def test_wal_in_header(self):
        report = CashflowReport(
            instrument_type="TEST",
            currency="USD",
            valuation_date=date(2025, 1, 1),
            cashflows=(),
            total_pv=Decimal("0"),
            total_undiscounted=Decimal("0"),
            weighted_average_life=3.1416,
        )
        table = format_cashflow_table(report)
        assert "3.1416" in table


# ---------------------------------------------------------------------------
# Pricer enrichment — TBA
# ---------------------------------------------------------------------------


class TestTbaEnrichment:
    def test_tba_has_interest_principal_prepayment(
        self, sample_tba: TbaContract, market_data: MarketData
    ):
        result = price_tba(sample_tba, market_data)

        types = {cf.cashflow_type for cf in result.cashflows}
        assert CashflowType.INTEREST in types
        assert CashflowType.PRINCIPAL in types
        assert CashflowType.PREPAYMENT in types

    def test_tba_cashflows_have_discount_factors(
        self, sample_tba: TbaContract, market_data: MarketData
    ):
        result = price_tba(sample_tba, market_data)

        for cf in result.cashflows:
            assert cf.discount_factor is not None
            assert 0 < cf.discount_factor <= 1.0

    def test_tba_cashflows_have_present_values(
        self, sample_tba: TbaContract, market_data: MarketData
    ):
        result = price_tba(sample_tba, market_data)

        for cf in result.cashflows:
            assert cf.present_value is not None

    def test_tba_labels_present(
        self, sample_tba: TbaContract, market_data: MarketData
    ):
        result = price_tba(sample_tba, market_data)

        labels = {cf.label for cf in result.cashflows}
        assert "interest" in labels
        assert "scheduled principal" in labels
        assert "prepayment" in labels


# ---------------------------------------------------------------------------
# Pricer enrichment — Inflation-linked bond
# ---------------------------------------------------------------------------


class TestInflationBondEnrichment:
    def test_has_coupon_and_principal(
        self, sample_tips_bond: InflationLinkedBond, market_data: MarketData
    ):
        result = price_inflation_linked_bond(sample_tips_bond, market_data)

        types = {cf.cashflow_type for cf in result.cashflows}
        assert CashflowType.COUPON in types
        assert CashflowType.PRINCIPAL in types

    def test_coupons_have_accrual_dates(
        self, sample_tips_bond: InflationLinkedBond, market_data: MarketData
    ):
        result = price_inflation_linked_bond(sample_tips_bond, market_data)

        coupons = [cf for cf in result.cashflows if cf.cashflow_type == CashflowType.COUPON]
        assert len(coupons) > 0
        for cf in coupons:
            assert cf.accrual_start is not None
            assert cf.accrual_end is not None
            assert cf.accrual_start < cf.accrual_end

    def test_all_have_discount_factors(
        self, sample_tips_bond: InflationLinkedBond, market_data: MarketData
    ):
        result = price_inflation_linked_bond(sample_tips_bond, market_data)

        for cf in result.cashflows:
            assert cf.discount_factor is not None
            assert cf.discount_factor > 0

    def test_all_have_present_values(
        self, sample_tips_bond: InflationLinkedBond, market_data: MarketData
    ):
        result = price_inflation_linked_bond(sample_tips_bond, market_data)

        for cf in result.cashflows:
            assert cf.present_value is not None


# ---------------------------------------------------------------------------
# Pricer enrichment — Cross-currency basis swap
# ---------------------------------------------------------------------------


class TestXccyBasisSwapEnrichment:
    def test_has_interest_type(self, sample_xccy_swap, market_data: MarketData):
        result = price_xccy_basis_swap(sample_xccy_swap, market_data)

        types = {cf.cashflow_type for cf in result.cashflows}
        assert CashflowType.INTEREST in types

    def test_has_notional_exchange(self, sample_xccy_swap, market_data: MarketData):
        # The sample swap has default initial_exchange=True and final_exchange=True
        result = price_xccy_basis_swap(sample_xccy_swap, market_data)

        types = {cf.cashflow_type for cf in result.cashflows}
        assert CashflowType.NOTIONAL_EXCHANGE in types

    def test_interest_has_accrual_dates(self, sample_xccy_swap, market_data: MarketData):
        result = price_xccy_basis_swap(sample_xccy_swap, market_data)

        interest_cfs = [
            cf for cf in result.cashflows if cf.cashflow_type == CashflowType.INTEREST
        ]
        assert len(interest_cfs) > 0
        for cf in interest_cfs:
            assert cf.accrual_start is not None
            assert cf.accrual_end is not None

    def test_all_have_discount_factors(self, sample_xccy_swap, market_data: MarketData):
        result = price_xccy_basis_swap(sample_xccy_swap, market_data)

        for cf in result.cashflows:
            assert cf.discount_factor is not None

    def test_labels_include_currency(self, sample_xccy_swap, market_data: MarketData):
        result = price_xccy_basis_swap(sample_xccy_swap, market_data)

        interest_cfs = [
            cf for cf in result.cashflows if cf.cashflow_type == CashflowType.INTEREST
        ]
        labels = {cf.label for cf in interest_cfs}
        # At least one label should contain "USD" and one "EUR"
        assert any("USD" in lbl for lbl in labels)
        assert any("EUR" in lbl for lbl in labels)


# ---------------------------------------------------------------------------
# End-to-end: build report from real pricer output
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_tba_report(self, sample_tba: TbaContract, market_data: MarketData):
        result = price_tba(sample_tba, market_data)
        report = build_cashflow_report(result, market_data.valuation_date)

        assert report.instrument_type == "TBA"
        assert report.currency == "USD"
        assert report.weighted_average_life > 0
        assert report.total_undiscounted > 0
        assert len(report.cashflows) > 0

    def test_inflation_bond_report(
        self, sample_tips_bond: InflationLinkedBond, market_data: MarketData
    ):
        result = price_inflation_linked_bond(sample_tips_bond, market_data)
        report = build_cashflow_report(result, market_data.valuation_date)

        assert report.instrument_type == "INFLATION_LINKED_BOND"
        assert report.weighted_average_life > 0
        assert report.total_pv > 0

    def test_format_tba_table(self, sample_tba: TbaContract, market_data: MarketData):
        result = price_tba(sample_tba, market_data)
        report = build_cashflow_report(result, market_data.valuation_date)
        table = format_cashflow_table(report)

        # Should be a multi-line string with meaningful content
        assert isinstance(table, str)
        assert len(table.splitlines()) > 5
        assert "TBA" in table
        assert "INTEREST" in table
