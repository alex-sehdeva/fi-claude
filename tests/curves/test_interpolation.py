"""Test curve interpolation — pure functions, no mocks needed."""

from datetime import date

import pytest

from fi_claude.curves.interpolation import interpolate_discount_factor
from fi_claude.data.common import Currency
from fi_claude.data.curves import CurveNode, DiscountCurve, InterpolationMethod


@pytest.fixture
def simple_curve() -> DiscountCurve:
    return DiscountCurve(
        reference_date=date(2025, 1, 1),
        currency=Currency.USD,
        nodes=(
            CurveNode(date=date(2025, 6, 1), value=0.98),
            CurveNode(date=date(2025, 12, 1), value=0.95),
        ),
        interpolation=InterpolationMethod.LINEAR,
    )


def test_exact_match(simple_curve: DiscountCurve):
    assert interpolate_discount_factor(simple_curve, date(2025, 6, 1)) == 0.98


def test_interpolation_midpoint(simple_curve: DiscountCurve):
    mid = date(2025, 9, 1)  # roughly midpoint
    result = interpolate_discount_factor(simple_curve, mid)
    assert 0.95 < result < 0.98


def test_extrapolation_before(simple_curve: DiscountCurve):
    result = interpolate_discount_factor(simple_curve, date(2025, 1, 1))
    assert result == 0.98  # flat extrapolation


def test_extrapolation_after(simple_curve: DiscountCurve):
    result = interpolate_discount_factor(simple_curve, date(2026, 6, 1))
    assert result == 0.95  # flat extrapolation


def test_empty_curve_raises():
    empty = DiscountCurve(
        reference_date=date(2025, 1, 1),
        currency=Currency.USD,
        nodes=(),
    )
    with pytest.raises(ValueError, match="empty curve"):
        interpolate_discount_factor(empty, date(2025, 6, 1))


def test_log_linear_positive():
    curve = DiscountCurve(
        reference_date=date(2025, 1, 1),
        currency=Currency.USD,
        nodes=(
            CurveNode(date=date(2025, 6, 1), value=0.98),
            CurveNode(date=date(2025, 12, 1), value=0.95),
        ),
        interpolation=InterpolationMethod.LOG_LINEAR,
    )
    result = interpolate_discount_factor(curve, date(2025, 9, 1))
    assert 0.95 < result < 0.98
    assert result > 0  # log-linear preserves positivity
