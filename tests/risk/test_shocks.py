"""Test the shock suite — pure functions, no mocks needed."""

from datetime import date
from decimal import Decimal

import pytest

from fi_claude.data.common import Currency
from fi_claude.data.curves import CurveNode, DiscountCurve, FxForwardCurve, InterpolationMethod
from fi_claude.data.market import MarketData
from fi_claude.risk.shocks import (
    CipPolicy,
    CurveShock,
    ShockSet,
    ShockType,
    apply_shocks,
    custom,
    flatten,
    fx_shock,
    inflation_shock,
    parallel,
    point_shock,
    scenario,
    steepen,
    twist,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def base_market() -> MarketData:
    ref = date(2025, 6, 15)
    return MarketData(
        valuation_date=ref,
        discount_curves={
            "USD": DiscountCurve(
                reference_date=ref,
                currency=Currency.USD,
                nodes=(
                    CurveNode(date=date(2025, 9, 15), value=0.9960),   # ~3m
                    CurveNode(date=date(2026, 6, 15), value=0.9550),   # ~1y
                    CurveNode(date=date(2028, 6, 15), value=0.8700),   # ~3y
                    CurveNode(date=date(2030, 6, 15), value=0.7800),   # ~5y
                    CurveNode(date=date(2035, 6, 15), value=0.6000),   # ~10y
                    CurveNode(date=date(2055, 6, 15), value=0.2500),   # ~30y
                ),
                interpolation=InterpolationMethod.LOG_LINEAR,
            ),
            "EUR": DiscountCurve(
                reference_date=ref,
                currency=Currency.EUR,
                nodes=(
                    CurveNode(date=date(2025, 9, 15), value=0.9975),
                    CurveNode(date=date(2026, 6, 15), value=0.9680),
                    CurveNode(date=date(2028, 6, 15), value=0.9000),
                    CurveNode(date=date(2030, 6, 15), value=0.8300),
                    CurveNode(date=date(2035, 6, 15), value=0.6700),
                    CurveNode(date=date(2055, 6, 15), value=0.3200),
                ),
                interpolation=InterpolationMethod.LOG_LINEAR,
            ),
        },
        fx_spot_rates={"EUR/USD": 1.0870},
        fx_curves={
            "EUR/USD": FxForwardCurve(
                reference_date=ref,
                base_currency=Currency.EUR,
                quote_currency=Currency.USD,
                spot_rate=1.0870,
                nodes=(
                    CurveNode(date=date(2026, 6, 15), value=0.0145),
                    CurveNode(date=date(2028, 6, 15), value=0.0350),
                ),
            ),
        },
        inflation_curves={},
    )


# ---------------------------------------------------------------------------
# Parallel shock tests
# ---------------------------------------------------------------------------


class TestParallelShock:
    def test_parallel_shifts_all_nodes(self, base_market: MarketData):
        s = scenario(rates=parallel("USD", 25))
        shocked = apply_shocks(base_market, s)

        orig = base_market.discount_curves["USD"]
        bump = shocked.discount_curves["USD"]

        # All bumped DFs should be lower (rates up → DFs down)
        for o, b in zip(orig.nodes, bump.nodes):
            assert b.value < o.value, f"Node {o.date}: expected DF to decrease"

    def test_parallel_zero_is_identity(self, base_market: MarketData):
        s = scenario(rates=parallel("USD", 0))
        shocked = apply_shocks(base_market, s)

        for o, b in zip(
            base_market.discount_curves["USD"].nodes,
            shocked.discount_curves["USD"].nodes,
        ):
            assert abs(o.value - b.value) < 1e-12

    def test_parallel_negative_raises_dfs(self, base_market: MarketData):
        s = scenario(rates=parallel("USD", -50))
        shocked = apply_shocks(base_market, s)

        orig = base_market.discount_curves["USD"]
        bump = shocked.discount_curves["USD"]

        for o, b in zip(orig.nodes, bump.nodes):
            assert b.value > o.value

    def test_multi_curve_parallel(self, base_market: MarketData):
        s = scenario(rates=parallel(("USD", "EUR"), 10))
        shocked = apply_shocks(base_market, s)

        for key in ("USD", "EUR"):
            for o, b in zip(
                base_market.discount_curves[key].nodes,
                shocked.discount_curves[key].nodes,
            ):
                assert b.value < o.value


# ---------------------------------------------------------------------------
# Steepen / flatten / twist tests
# ---------------------------------------------------------------------------


class TestShapeShocks:
    def test_steepen_long_end_moves_more(self, base_market: MarketData):
        s = scenario(rates=steepen("USD", short_bps=0, long_bps=50))
        shocked = apply_shocks(base_market, s)

        orig = base_market.discount_curves["USD"].nodes
        bump = shocked.discount_curves["USD"].nodes

        # Short end barely moves, long end moves a lot
        short_delta = abs(orig[0].value - bump[0].value)
        long_delta = abs(orig[-1].value - bump[-1].value)
        assert long_delta > short_delta * 5  # long end should move much more

    def test_flatten_short_end_moves_more(self, base_market: MarketData):
        # Flatten inverts: short gets long_bps, long gets short_bps
        s = scenario(rates=flatten("USD", short_bps=0, long_bps=50))
        shocked = apply_shocks(base_market, s)

        orig = base_market.discount_curves["USD"].nodes
        bump = shocked.discount_curves["USD"].nodes

        short_delta = abs(orig[0].value - bump[0].value)
        long_delta = abs(orig[-1].value - bump[-1].value)
        assert short_delta > long_delta  # flatten: short moves more

    def test_twist_pivot_unchanged(self, base_market: MarketData):
        s = scenario(rates=twist("USD", pivot_years=5.0, short_bps=-20, long_bps=20))
        shocked = apply_shocks(base_market, s)

        orig = base_market.discount_curves["USD"]
        bump = shocked.discount_curves["USD"]

        # The 5y node should barely move (it's at the pivot)
        # Find the ~5y node (index 3: 2030-06-15)
        delta_5y = abs(orig.nodes[3].value - bump.nodes[3].value)
        delta_short = abs(orig.nodes[0].value - bump.nodes[0].value)
        delta_long = abs(orig.nodes[-1].value - bump.nodes[-1].value)

        assert delta_5y < delta_short
        assert delta_5y < delta_long

    def test_twist_directions(self, base_market: MarketData):
        s = scenario(rates=twist("USD", pivot_years=5.0, short_bps=-20, long_bps=20))
        shocked = apply_shocks(base_market, s)

        orig = base_market.discount_curves["USD"]
        bump = shocked.discount_curves["USD"]

        # Short end: rates down → DF up
        assert bump.nodes[0].value > orig.nodes[0].value
        # Long end: rates up → DF down
        assert bump.nodes[-1].value < orig.nodes[-1].value


# ---------------------------------------------------------------------------
# Point shock tests
# ---------------------------------------------------------------------------


class TestPointShock:
    def test_point_concentrated(self, base_market: MarketData):
        s = scenario(rates=point_shock("USD", target_years=5.0, bps=100, width=0.5))
        shocked = apply_shocks(base_market, s)

        orig = base_market.discount_curves["USD"]
        bump = shocked.discount_curves["USD"]

        # 5y node (index 3) should move the most
        deltas = [
            abs(o.value - b.value) for o, b in zip(orig.nodes, bump.nodes)
        ]
        max_idx = deltas.index(max(deltas))
        assert max_idx == 3  # 5y node

    def test_point_far_nodes_barely_move(self, base_market: MarketData):
        s = scenario(rates=point_shock("USD", target_years=5.0, bps=100, width=0.5))
        shocked = apply_shocks(base_market, s)

        orig = base_market.discount_curves["USD"]
        bump = shocked.discount_curves["USD"]

        # 3m node should barely move
        delta_3m = abs(orig.nodes[0].value - bump.nodes[0].value)
        assert delta_3m < 1e-6


# ---------------------------------------------------------------------------
# Custom shock tests
# ---------------------------------------------------------------------------


class TestCustomShock:
    def test_custom_per_tenor(self, base_market: MarketData):
        s = scenario(rates=custom("USD", {1.0: 10, 5.0: 25, 10.0: 50}))
        shocked = apply_shocks(base_market, s)

        orig = base_market.discount_curves["USD"]
        bump = shocked.discount_curves["USD"]

        # All should move down (positive bps = rates up = DFs down)
        for o, b in zip(orig.nodes, bump.nodes):
            assert b.value <= o.value + 1e-10


# ---------------------------------------------------------------------------
# FX shock tests
# ---------------------------------------------------------------------------


class TestFxShock:
    def test_fx_pct_shock(self, base_market: MarketData):
        s = scenario(fx=fx_shock("EUR/USD", pct=-5.0))
        shocked = apply_shocks(base_market, s)

        assert shocked.fx_spot_rates["EUR/USD"] == pytest.approx(
            1.0870 * 0.95, rel=1e-10
        )

    def test_fx_absolute_shock(self, base_market: MarketData):
        s = scenario(fx=fx_shock("EUR/USD", absolute=-0.05))
        shocked = apply_shocks(base_market, s)

        assert shocked.fx_spot_rates["EUR/USD"] == pytest.approx(1.0370, rel=1e-10)


# ---------------------------------------------------------------------------
# CIP coherence tests
# ---------------------------------------------------------------------------


class TestCipCoherence:
    def test_cip_adjusts_fx_forwards(self, base_market: MarketData):
        """When rates are shocked, FX forwards must adjust under ENFORCE."""
        s = scenario(
            rates=parallel("USD", 50),
            cip=CipPolicy.ENFORCE,
        )
        shocked = apply_shocks(base_market, s)

        # FX forward points should change (CIP adjustment)
        orig_fwd = base_market.fx_curves["EUR/USD"].nodes[0].value
        bump_fwd = shocked.fx_curves["EUR/USD"].nodes[0].value

        assert orig_fwd != bump_fwd

    def test_cip_ignore_leaves_fx_unchanged(self, base_market: MarketData):
        """IGNORE policy: rate shocks don't touch FX."""
        s = scenario(
            rates=parallel("USD", 50),
            cip=CipPolicy.IGNORE,
        )
        shocked = apply_shocks(base_market, s)

        # FX forward points unchanged
        for o, b in zip(
            base_market.fx_curves["EUR/USD"].nodes,
            shocked.fx_curves["EUR/USD"].nodes,
        ):
            assert o.value == b.value

    def test_cip_direction(self, base_market: MarketData):
        """USD rates up → df_USD down → EUR/USD forward = S * df_quote / df_base
        = S * df_USD / df_EUR → falls (quote=USD weakens at forward horizon)."""
        s = scenario(
            rates=parallel("USD", 100),
            cip=CipPolicy.ENFORCE,
        )
        shocked = apply_shocks(base_market, s)

        # CIP: F = S × df_quote(t) / df_base(t) where base=EUR, quote=USD
        # USD rates up → df_USD down → F = S × df_USD/df_EUR decreases
        # → forward points (F - S) decrease
        orig_fwd = base_market.fx_curves["EUR/USD"].nodes[0].value
        bump_fwd = shocked.fx_curves["EUR/USD"].nodes[0].value
        assert bump_fwd < orig_fwd


# ---------------------------------------------------------------------------
# Composition tests
# ---------------------------------------------------------------------------


class TestComposition:
    def test_multi_shock_scenario(self, base_market: MarketData):
        """Compose rate + FX + inflation shocks."""
        s = scenario(
            "Fed hike + EUR steepen + EURUSD drop",
            rates=(parallel("USD", 25), steepen("EUR", 0, 15)),
            fx=fx_shock("EUR/USD", pct=-2.0),
        )
        shocked = apply_shocks(base_market, s)

        # USD DFs should be lower
        assert shocked.discount_curves["USD"].nodes[0].value < \
               base_market.discount_curves["USD"].nodes[0].value

        # EUR/USD should be lower
        assert shocked.fx_spot_rates["EUR/USD"] < base_market.fx_spot_rates["EUR/USD"]

    def test_scenario_label(self, base_market: MarketData):
        s = scenario("test label", rates=parallel("USD", 10))
        assert s.label == "test label"

    def test_original_market_unchanged(self, base_market: MarketData):
        """Verify immutability: original market is never mutated."""
        orig_usd_3m = base_market.discount_curves["USD"].nodes[0].value

        s = scenario(rates=parallel("USD", 100))
        _ = apply_shocks(base_market, s)

        assert base_market.discount_curves["USD"].nodes[0].value == orig_usd_3m


# ---------------------------------------------------------------------------
# Convenience constructor tests
# ---------------------------------------------------------------------------


class TestConvenience:
    def test_string_curve_arg(self):
        s = parallel("USD", 25)
        assert s.curves == ("USD",)

    def test_tuple_curve_arg(self):
        s = parallel(("USD", "EUR"), 25)
        assert s.curves == ("USD", "EUR")

    def test_scenario_single_shock(self):
        s = scenario(rates=parallel("USD", 10))
        assert len(s.rate_shocks) == 1

    def test_scenario_tuple_shocks(self):
        s = scenario(rates=(parallel("USD", 10), steepen("EUR", 0, 20)))
        assert len(s.rate_shocks) == 2

    def test_scenario_default_cip(self):
        s = scenario(rates=parallel("USD", 10))
        assert s.cip == CipPolicy.ENFORCE
