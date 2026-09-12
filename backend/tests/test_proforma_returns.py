"""F2: return-metric primitives — XIRR against Excel's documented reference
example, exact closed-form periodic IRR cases, PMT against the standard
mortgage constant, payback/NPV/multiple mechanics.
"""

from datetime import date

import pytest

from app.services.proforma.debt import monthly_payment
from app.services.proforma.returns import (
    equity_multiple,
    irr_diagnostics,
    npv,
    payback_period_years,
    periodic_irr,
    periodic_irr_roots,
    profitability_index,
    select_economic_root,
    sign_changes,
    xirr,
    xirr_roots,
)

# Two-root series: (x - 1.01)(x - 1.03) with x = 1 + monthly rate, i.e.
# -1000, +2040, -1040.3 -> monthly IRRs of exactly 1% and 3%.
TWO_ROOT_FLOWS = [-1000.0, 2040.0, -1040.3]
TWO_ROOTS_ANNUAL = [1.01**12 - 1, 1.03**12 - 1]


def test_xirr_matches_excel_reference_example():
    # The example from Microsoft's XIRR documentation: result 0.373362535.
    dates = [
        date(2008, 1, 1),
        date(2008, 3, 1),
        date(2008, 10, 30),
        date(2009, 2, 15),
        date(2009, 4, 1),
    ]
    amounts = [-10000, 2750, 4250, 3250, 2750]
    assert xirr(dates, amounts) == pytest.approx(0.373362535, abs=1e-6)


def test_xirr_handles_unsorted_input_and_no_sign_change():
    dates = [date(2020, 6, 1), date(2020, 1, 1)]
    amounts = [11000, -10000]
    result = xirr(dates, amounts)
    # 10% over 152 days at actual/365: (1+r)^(152/365) = 1.1
    assert result == pytest.approx(1.1 ** (365 / 152) - 1, rel=1e-6)
    assert xirr([date(2020, 1, 1), date(2020, 6, 1)], [100, 100]) is None


def test_periodic_irr_exact_two_flow_case():
    # -100 now, +121 in 24 months: monthly (1.21)^(1/24)-1, annual = 1.21^0.5-1 = 10%.
    flows = [-100.0] + [0.0] * 23 + [121.0]
    assert periodic_irr(flows) == pytest.approx(0.10, abs=1e-9)


def test_periodic_irr_level_coupon_at_par():
    # Par bond logic: monthly IRR equals the coupon rate exactly.
    flows = [-1000.0] + [10.0] * 59 + [1010.0]
    assert periodic_irr(flows) == pytest.approx(1.01**12 - 1, abs=1e-9)


def test_periodic_irr_undefined_cases():
    assert periodic_irr([-100, -50]) is None
    assert periodic_irr([100, 50]) is None
    assert periodic_irr([]) is None


def test_sign_changes_ignores_zeros():
    assert sign_changes([-100, 0, 0, 50, 60]) == 1
    assert sign_changes([-100, 50, -20, 70]) == 3
    assert sign_changes([-100, -50]) == 0
    assert sign_changes([]) == 0


def test_root_scan_finds_both_roots_of_a_two_root_series():
    roots = periodic_irr_roots(TWO_ROOT_FLOWS)
    assert len(roots) == 2
    assert roots[0] == pytest.approx(TWO_ROOTS_ANNUAL[0], abs=1e-7)
    assert roots[1] == pytest.approx(TWO_ROOTS_ANNUAL[1], abs=1e-7)
    # A conventional series has exactly one root, and it is the IRR.
    flows = [-100.0] + [0.0] * 23 + [121.0]
    assert periodic_irr_roots(flows) == [pytest.approx(0.10, abs=1e-7)]
    assert periodic_irr_roots([-100, -50]) == []


def test_xirr_root_scan_matches_excel_reference():
    dates = [date(2008, 1, 1), date(2008, 3, 1), date(2008, 10, 30),
             date(2009, 2, 15), date(2009, 4, 1)]
    roots = xirr_roots(dates, [-10000, 2750, 4250, 3250, 2750])
    assert roots == [pytest.approx(0.373362535, abs=1e-6)]


def test_economic_root_rule():
    # Anchored (levered series): nearest the anchor.
    assert select_economic_root(TWO_ROOTS_ANNUAL, anchor=0.40) == TWO_ROOTS_ANNUAL[1]
    assert select_economic_root(TWO_ROOTS_ANNUAL, anchor=0.05) == TWO_ROOTS_ANNUAL[0]
    # Unanchored: nearest 0%.
    assert select_economic_root([-0.95, 0.30, 2.5], anchor=None) == 0.30
    with pytest.raises(ValueError):
        select_economic_root([], anchor=None)


def test_irr_diagnostics_only_for_multi_root_series():
    # One sign change: never touched, regardless of roots.
    assert irr_diagnostics([-100.0] + [0.0] * 23 + [121.0]) is None
    # Several sign changes but a single root in the band: still None (the
    # Newton answer is the only candidate) — the commercial_rollover shape.
    assert irr_diagnostics([-100, 10, -5, 10, 10, 120]) is None
    diag = irr_diagnostics(TWO_ROOT_FLOWS, anchor=0.40)
    assert diag["signChanges"] == 2
    assert diag["roots"] == [pytest.approx(r, abs=1e-7) for r in TWO_ROOTS_ANNUAL]
    assert diag["selected"] == pytest.approx(TWO_ROOTS_ANNUAL[1], abs=1e-7)
    assert diag["otherRoots"] == [pytest.approx(TWO_ROOTS_ANNUAL[0], abs=1e-7)]


def test_periodic_irr_itself_is_unchanged_for_one_sign_change():
    """The solver is not rerouted: single-sign-change series get the same
    Newton/bisection answer as before (baseline)."""
    flows = [-1000.0] + [10.0] * 59 + [1010.0]
    assert periodic_irr(flows) == pytest.approx(1.01**12 - 1, abs=1e-9)


def test_monthly_payment_standard_mortgage_constant():
    # $300,000, 6%, 30 years -> the textbook $1,798.65 payment.
    assert monthly_payment(300000, 0.06, 30) == pytest.approx(1798.65, abs=0.01)
    assert monthly_payment(120000, 0.0, 10) == pytest.approx(1000.0)
    assert monthly_payment(0, 0.06, 30) == 0.0


def test_equity_multiple_and_payback():
    flows = [-400000.0] + [3666.6667] * 59 + [3666.6667 + 400000.0]
    assert equity_multiple(flows) == pytest.approx(1.55, abs=1e-6)
    # Cumulative crosses zero inside the exit month.
    assert payback_period_years(flows) == pytest.approx(4.955, abs=0.01)


def test_npv_and_profitability_index_hand_calc():
    # See fixtures/analytic_acquisition.json comment block for the algebra.
    flows = [-400000.0] + [3666.6667] * 59 + [3666.6667 + 400000.0]
    assert npv(0.10, flows) == pytest.approx(22677, abs=25)
    assert profitability_index(0.10, flows) == pytest.approx(1.0567, abs=1e-3)
