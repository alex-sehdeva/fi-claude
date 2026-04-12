"""Test that data models are truly immutable and validate correctly."""

from datetime import date
from decimal import Decimal

import pytest

from fi_claude.data.common import Currency, DayCountConvention, PayReceive
from fi_claude.data.curves import CurveNode, DiscountCurve, InterpolationMethod
from fi_claude.data.instruments import BrlPreCdiSwap


def test_cashflow_frozen():
    from fi_claude.data.common import Cashflow

    cf = Cashflow(payment_date=date(2025, 7, 15), amount=Decimal("100"), currency=Currency.USD)
    with pytest.raises(Exception):
        cf.amount = Decimal("200")  # type: ignore[misc]


def test_curve_must_be_sorted():
    with pytest.raises(ValueError, match="sorted by date"):
        DiscountCurve(
            reference_date=date(2025, 1, 1),
            currency=Currency.USD,
            nodes=(
                CurveNode(date=date(2025, 12, 1), value=0.95),
                CurveNode(date=date(2025, 6, 1), value=0.98),  # out of order
            ),
        )


def test_curve_sorted_ok():
    curve = DiscountCurve(
        reference_date=date(2025, 1, 1),
        currency=Currency.USD,
        nodes=(
            CurveNode(date=date(2025, 6, 1), value=0.98),
            CurveNode(date=date(2025, 12, 1), value=0.95),
        ),
    )
    assert len(curve.nodes) == 2


def test_swap_frozen():
    swap = BrlPreCdiSwap(
        notional=Decimal("1000000"),
        fixed_rate=0.1350,
        start_date=date(2025, 1, 1),
        end_date=date(2026, 1, 1),
        pay_receive_fixed=PayReceive.PAY,
    )
    with pytest.raises(Exception):
        swap.fixed_rate = 0.14  # type: ignore[misc]


def test_swap_defaults():
    swap = BrlPreCdiSwap(
        notional=Decimal("1000000"),
        fixed_rate=0.1350,
        start_date=date(2025, 1, 1),
        end_date=date(2026, 1, 1),
        pay_receive_fixed=PayReceive.PAY,
    )
    assert swap.day_count == DayCountConvention.BUS_252
    assert swap.currency == Currency.BRL
