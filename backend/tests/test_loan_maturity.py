"""Loan maturity inside the hold (roadmap #11): the balloon is refinanced.
loanTermYears used to be ignored, so a 10-year hold on a 5-year loan
never faced its maturity."""

import json
from pathlib import Path

import pytest

from app.services import excel_model_export
from app.services.proforma import debt, engine

_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def analytic():
    # $1M price, NOI 80k flat, $600k IO at 6% for the whole hold, 8% exit cap.
    data = json.loads((_FIXTURES / "analytic_acquisition.json").read_text())
    data.pop("_comment", None)
    return data


def test_balloon_refinances_into_a_newly_sized_amortizing_loan(analytic):
    deal = dict(analytic, loanTermYears=3, refiCostsPct=0.01)
    result = engine.compute(deal)
    refi, stmt = result["maturityRefinance"], result["statement"]
    # Month 36: IO balloon 600k; forward NOI 80k / 8% = 1M value; 60% LTV = 600k
    # (binds before DSCR / debt yield). Costs 1% = 6,000 paid by equity.
    assert refi["month"] == 36 and refi["balloon"] == pytest.approx(600_000)
    assert refi["newLoan"] == pytest.approx(600_000) and refi["costs"] == pytest.approx(6_000)
    noi_month = 80_000 / 12
    assert stmt["levered"][36] == pytest.approx(noi_month - 3_000 - 6_000)
    # From month 37 the new loan amortizes (no IO) at 6% / 30 years.
    payment = debt.monthly_payment(600_000, 0.06, 30)
    assert stmt["debtService"][37] == pytest.approx(payment)
    assert stmt["levered"][37] == pytest.approx(noi_month - payment)
    # Exit pays off the new loan's balance after 24 payments.
    expected_balance = debt.amortization_schedule(600_000, 0.06, 30, 0, 24)[-1].balance
    assert stmt["loanBalance"][60] == pytest.approx(expected_balance)
    assert any("matures in month 36" in w for w in result["warnings"])


def test_no_refinance_when_the_term_covers_the_hold_or_is_blank(analytic):
    plain = engine.compute(dict(analytic, loanTermYears=None))
    assert plain["maturityRefinance"] is None
    assert engine.compute(dict(analytic, loanTermYears=5))["maturityRefinance"] is None  # matures at exit
    assert engine.compute(dict(analytic, loanTermYears=10))["outputs"] == plain["outputs"]


def test_development_term_runs_from_the_permanent_takeout():
    deal = json.loads((_FIXTURES / "analytic_development.json").read_text())
    base = engine.compute(dict(deal, loanTermYears=None))
    takeout = base["statement"]["stabilizationMonth"]
    refi = engine.compute(dict(deal, loanTermYears=3))["maturityRefinance"]
    assert refi["month"] == takeout + 36 - 1


def test_excel_export_refuses_a_mid_hold_refinance(analytic):
    with pytest.raises(excel_model_export.UnsupportedModelFeatures):
        excel_model_export.build_model_workbook(dict(analytic, loanTermYears=3))
