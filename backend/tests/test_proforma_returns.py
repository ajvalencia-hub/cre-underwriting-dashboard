"""F2: return-metric primitives — XIRR against Excel's documented reference
example, exact closed-form periodic IRR cases, PMT against the standard
mortgage constant, payback/NPV/multiple mechanics.
"""

from datetime import date

import pytest

from app.services.proforma.debt import monthly_payment
from app.services.proforma.returns import (
    equity_multiple,
    npv,
    payback_period_years,
    periodic_irr,
    profitability_index,
    xirr,
)


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
