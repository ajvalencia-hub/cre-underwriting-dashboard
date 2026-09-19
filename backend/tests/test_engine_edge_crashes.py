"""Crashes found by the property tests (roadmap #32). Each case used to
raise ZeroDivisionError, which Compute returns as a 500."""

import json
from pathlib import Path

import pytest

from app.services.proforma import debt
from app.services.proforma.engine import compute

_FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> dict:
    data = json.loads((_FIXTURES / name).read_text())
    data.pop("_comment", None)
    return data


def test_payment_at_a_rate_too_small_to_register():
    assert debt.monthly_payment(1_200_000, 1.4e-45, 10) == pytest.approx(10_000)


def test_loan_year_without_debt_service_is_skipped_in_min_dscr():
    # A 1-year amortization repays the loan in year one; a 10-year term on an
    # 11-year hold then refinances at month 120, leaving years with no debt
    # service between the two.
    deal = dict(
        _fixture("analytic_acquisition.json"),
        amortYears=1, ioMonths=0, holdPeriodYears=11, loanTermYears=10,
    )
    outputs = compute(deal)["outputs"]
    assert outputs["minDscr"] > 0


def test_full_credit_loss_has_no_break_even_occupancy():
    deal = dict(_fixture("analytic_development.json"), creditLossPct=1.0)
    outputs = compute(deal)["outputs"]
    assert "breakEvenOccupancy" not in outputs


def test_floating_schedule_at_a_rate_too_small_to_register():
    schedule = debt.amortization_schedule_floating(120_000, [1.4e-45] * 24, 1, 0, 24)
    assert schedule[0].principal == pytest.approx(10_000)


def test_zero_amortization_is_interest_only():
    # Owner decision 2026-09-19: it used to repay the whole loan in month 1.
    assert debt.monthly_payment(600_000, 0.06, 0) == pytest.approx(3_000)
    schedule = debt.amortization_schedule(600_000, 0.06, 0, 0, 60)
    assert all(m.principal == 0 and m.balance == 600_000 for m in schedule)
    outputs = compute(dict(_fixture("analytic_acquisition.json"), amortYears=0, ioMonths=0))["outputs"]
    # The analytic deal is interest-only for its whole hold already.
    assert outputs["leveredIrr"] == pytest.approx(compute(_fixture("analytic_acquisition.json"))["outputs"]["leveredIrr"])
