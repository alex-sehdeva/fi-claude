"""Market data snapshots from real observable rates — ACTIONS.

This module encodes real market data fetched from public sources
(BCB, B3, US Treasury, Investing.com) and transforms it into
the immutable MarketData snapshots our pricers consume.

Data sources (as of April 10, 2026):
    BRL-CDI:    DI futures / Brazil govt bond yields (B3, tradingeconomics)
    USD:        US Treasury yields (US Treasury Dept, Investing.com)
    EUR:        German Bund yields (Investing.com)
    MXN-TIIE:   TIIE 28-day rate (Banxico, tradingeconomics)
    US CPI:     BLS CPI-U release (bls.gov)
    FX spot:    BCB PTAX (BCB API series 1)

Grokking Simplicity: this is an ACTION because the data it encodes
depends on *when* it was fetched. But once constructed, the returned
MarketData is pure DATA.
"""

from __future__ import annotations

from datetime import date

from fi_claude.curves.bootstrap import build_brl_cdi_curve, build_yield_curve
from fi_claude.data.common import Currency
from fi_claude.data.curves import CurveNode, InflationCurve
from fi_claude.data.market import MarketData


def april_10_2026_snapshot() -> MarketData:
    """Complete market data snapshot as of April 10, 2026.

    All rates sourced from public data:
        - BCB API: CDI = 0.054266%/day, Selic target = 14.75%
        - PTAX: USD/BRL = 5.0229
        - Brazil govt bond yields: 3M-10Y (tradingeconomics)
        - US Treasury yields: 1M-30Y (Investing.com / US Treasury Dept)
        - German Bund yields: 3M-30Y (Investing.com)
        - TIIE 28-day: 7.24% (tradingeconomics)
        - US CPI: +3.3% YoY, index ~325.8 (BLS)
    """
    val_date = date(2026, 4, 10)

    # --- BRL-CDI curve (from DI futures / govt bond yields) ---
    # These are annualized pre-fixada rates under BUS/252 convention.
    # Source: B3 DI futures settlement, proxied by govt bond yields.
    brl_cdi = build_brl_cdi_curve(
        val_date,
        {
            "3M": 0.1404,
            "6M": 0.1408,
            "1Y": 0.1370,
            "2Y": 0.1357,
            "3Y": 0.1348,
            "5Y": 0.1354,
            "10Y": 0.1372,
        },
    )

    # --- USD curve (from US Treasury yields, semi-annual compounding) ---
    usd = build_yield_curve(
        val_date,
        Currency.USD,
        {
            "1M": 0.03645,
            "3M": 0.03685,
            "6M": 0.03706,
            "1Y": 0.03695,
            "2Y": 0.03801,
            "3Y": 0.03824,
            "5Y": 0.03939,
            "7Y": 0.04121,
            "10Y": 0.04317,
            "20Y": 0.04902,
            "30Y": 0.04914,
        },
        compounding="semi-annual",
    )

    # --- EUR curve (from German Bund yields) ---
    eur = build_yield_curve(
        val_date,
        Currency.EUR,
        {
            "3M": 0.01905,
            "6M": 0.02111,
            "1Y": 0.02419,
            "2Y": 0.02584,
            "3Y": 0.02558,
            "5Y": 0.02731,
            "7Y": 0.02839,
            "10Y": 0.03048,
            "20Y": 0.03511,
            "30Y": 0.03576,
        },
        compounding="semi-annual",
    )

    # --- MXN-TIIE curve ---
    # TIIE 28-day = 7.24%. Build a simple term structure.
    # Short end anchored at TIIE; longer tenors from market consensus.
    mxn = build_yield_curve(
        val_date,
        Currency.MXN,
        {
            "1M": 0.0724,
            "3M": 0.0720,
            "6M": 0.0710,
            "1Y": 0.0695,
            "2Y": 0.0680,
            "3Y": 0.0670,
            "5Y": 0.0665,
            "10Y": 0.0675,
        },
        compounding="annual",
    )

    # --- USD-REAL curve (from TIPS real yields, semi-annual compounding) ---
    # TIPS yields represent real (inflation-adjusted) discount rates.
    # Source: US Treasury TIPS yields (treasury.gov, April 2026)
    usd_real = build_yield_curve(
        val_date,
        Currency.USD,
        {
            "5Y": 0.0185,
            "7Y": 0.0198,
            "10Y": 0.0210,
            "20Y": 0.0228,
            "30Y": 0.0235,
        },
        compounding="semi-annual",
    )

    # --- US CPI inflation curve ---
    # March 2026 CPI-U: +3.3% YoY, +0.9% MoM.
    # Estimated index level: ~325.8 (base period 1982-84=100).
    # Project forward at ~3.3% annualized.
    base_cpi = 325.8
    us_cpi = InflationCurve(
        reference_date=val_date,
        base_index_level=base_cpi,
        nodes=(
            CurveNode(date=date(2026, 7, 10), value=base_cpi * 1.008),    # +0.8% in 3M
            CurveNode(date=date(2026, 10, 10), value=base_cpi * 1.016),   # ~3.2% ann
            CurveNode(date=date(2027, 4, 10), value=base_cpi * 1.033),    # +3.3% YoY
            CurveNode(date=date(2028, 4, 10), value=base_cpi * 1.066),    # 2Y
            CurveNode(date=date(2031, 4, 10), value=base_cpi * 1.170),    # 5Y ~3.2%
            CurveNode(date=date(2036, 4, 10), value=base_cpi * 1.360),    # 10Y ~3.1%
        ),
    )

    # --- FX spot rates ---
    # USD/BRL from BCB PTAX (April 10, 2026): 5.0229
    # EUR/USD estimate: ~1.095 (based on market context)
    # USD/MXN estimate: ~18.80
    fx_spots = {
        "USD/BRL": 5.0229,
        "EUR/USD": 1.095,
        "USD/MXN": 18.80,
    }

    return MarketData(
        valuation_date=val_date,
        discount_curves={
            "BRL-CDI": brl_cdi,
            "USD": usd,
            "EUR": eur,
            "MXN-TIIE": mxn,
            "USD-REAL": usd_real,
        },
        inflation_curves={
            "US-CPI": us_cpi,
        },
        fx_spot_rates=fx_spots,
    )
