"""Tests for market data snapshots with real April 2026 data."""

from datetime import date

import pytest

from fi_claude.market.snapshots import april_10_2026_snapshot


class TestApril2026Snapshot:
    @pytest.fixture
    def market(self):
        return april_10_2026_snapshot()

    def test_valuation_date(self, market):
        assert market.valuation_date == date(2026, 4, 10)

    def test_has_all_discount_curves(self, market):
        assert "BRL-CDI" in market.discount_curves
        assert "USD" in market.discount_curves
        assert "EUR" in market.discount_curves
        assert "MXN-TIIE" in market.discount_curves

    def test_has_inflation_curve(self, market):
        assert "US-CPI" in market.inflation_curves

    def test_has_fx_spots(self, market):
        assert "USD/BRL" in market.fx_spot_rates
        assert "EUR/USD" in market.fx_spot_rates
        assert "USD/MXN" in market.fx_spot_rates

    def test_brl_cdi_curve_shape(self, market):
        curve = market.discount_curves["BRL-CDI"]
        assert len(curve.nodes) == 8  # T=0 + 3M to 10Y
        # T=0 should be 1.0, rest between 0 and 1
        assert curve.nodes[0].value == 1.0
        for node in curve.nodes[1:]:
            assert 0 < node.value < 1

    def test_brl_cdi_rates_in_range(self, market):
        """Implied rates should be in the 13-15% range (April 2026 levels)."""
        curve = market.discount_curves["BRL-CDI"]
        ref = curve.reference_date
        for node in curve.nodes:
            cal_days = (node.date - ref).days
            bd = round(cal_days * 252 / 365.25)
            if bd > 0:
                implied = (1.0 / node.value) ** (252.0 / bd) - 1.0
                assert 0.13 < implied < 0.15, f"Implied rate {implied:.4f} out of range"

    def test_usd_rates_much_lower_than_brl(self, market):
        """At comparable tenors, USD DFs should be higher (lower rates)."""
        from fi_claude.curves.interpolation import interpolate_discount_factor
        from datetime import timedelta

        # Compare 5Y discount factors
        target = market.valuation_date + timedelta(days=round(5 * 365.25))
        brl_df = interpolate_discount_factor(market.discount_curves["BRL-CDI"], target)
        usd_df = interpolate_discount_factor(market.discount_curves["USD"], target)
        # USD ~4% vs BRL ~13.5% → USD DF should be much higher
        assert usd_df > brl_df
        assert usd_df > 0.80  # USD 5Y DF ~ 0.82
        assert brl_df < 0.55  # BRL 5Y DF ~ 0.52

    def test_fx_spot_usdbrl_reasonable(self, market):
        # April 2026 PTAX was ~5.02
        assert 4.5 < market.fx_spot_rates["USD/BRL"] < 6.0

    def test_cpi_index_level_reasonable(self, market):
        cpi = market.inflation_curves["US-CPI"]
        # CPI-U base should be in the 320-330 range for early 2026
        assert 320 < cpi.base_index_level < 335

    def test_prices_brl_swap(self, market):
        """Smoke test: can we price a swap with this market data?"""
        from decimal import Decimal
        from fi_claude.data.instruments import BrlPreCdiSwap
        from fi_claude.data.common import PayReceive
        from fi_claude.pricers.brl_pre_cdi import price_brl_pre_cdi_swap

        swap = BrlPreCdiSwap(
            notional=Decimal("10_000_000"),
            fixed_rate=0.1357,  # 2Y market rate
            start_date=date(2026, 4, 10),
            end_date=date(2028, 4, 10),
            pay_receive_fixed=PayReceive.PAY,
        )
        result = price_brl_pre_cdi_swap(swap, market, business_days=504)
        # Verify pricing runs without error and produces reasonable output
        assert result.instrument_type == "BRL_PRE_CDI_SWAP"
        assert result.details["df_start"] == pytest.approx(1.0, abs=0.01)
        assert 0.5 < result.details["df_end"] < 1.0

    def test_shock_changes_npv(self, market):
        """Shocking the curve should change the swap NPV."""
        from decimal import Decimal
        from fi_claude.data.instruments import BrlPreCdiSwap
        from fi_claude.data.common import PayReceive
        from fi_claude.pricers.brl_pre_cdi import price_brl_pre_cdi_swap
        from fi_claude.risk.shocks import apply_shocks, parallel, scenario

        swap = BrlPreCdiSwap(
            notional=Decimal("10_000_000"),
            fixed_rate=0.1357,
            start_date=date(2026, 4, 10),
            end_date=date(2028, 4, 10),
            pay_receive_fixed=PayReceive.PAY,
        )
        base = price_brl_pre_cdi_swap(swap, market, business_days=504)
        shocked = apply_shocks(market, scenario(rates=parallel("BRL-CDI", 50)))
        bumped = price_brl_pre_cdi_swap(swap, shocked, business_days=504)
        # +50bp should change the NPV
        assert float(bumped.present_value) != float(base.present_value)
