"""Exit mechanics (roadmap #24): trailing vs forward NOI for the exit value,
and a prepayment cost on the loan repaid at sale."""

import json
from pathlib import Path

import pytest

from app.services.proforma import engine

_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def growing():
    from tests.parity.export_case import AMORTIZING_GROWTH_INPUTS

    return dict(AMORTIZING_GROWTH_INPUTS)  # rents +3%/yr, 5-yr hold, amortizing loan


def test_trailing_basis_caps_the_last_twelve_months_of_the_hold(growing):
    result = engine.compute(dict(growing, exitNoiBasis="trailing"))
    stmt = result["statement"]
    trailing = sum(stmt["noi"][49:61])
    assert result["outputs"]["terminalValue"] == pytest.approx(trailing / growing["exitCapRatePct"])
    forward = engine.compute(growing)["outputs"]["terminalValue"]
    assert result["outputs"]["terminalValue"] < forward  # growing NOI: trailing is lower


def test_prepayment_cost_reduces_levered_proceeds_only(growing):
    base = engine.compute(growing)
    penalized = engine.compute(dict(growing, prepaymentPenaltyPct=0.01))
    exit_balance = base["statement"]["loanBalance"][60]
    assert penalized["outputs"]["prepaymentCost"] == pytest.approx(0.01 * exit_balance)
    assert penalized["outputs"]["netSaleProceeds"] == pytest.approx(
        base["outputs"]["netSaleProceeds"] - 0.01 * exit_balance
    )
    assert penalized["outputs"]["unleveredIrr"] == pytest.approx(base["outputs"]["unleveredIrr"])
    assert penalized["outputs"]["leveredIrr"] < base["outputs"]["leveredIrr"]


def test_defaults_are_unchanged(growing):
    assert engine.compute(dict(growing, exitNoiBasis="forward", prepaymentPenaltyPct=0))["outputs"] == (
        engine.compute(growing)["outputs"]
    )


def test_excel_export_refuses_what_it_does_not_mirror(growing):
    from app.services import excel_model_export

    for extra in ({"exitNoiBasis": "trailing"}, {"prepaymentPenaltyPct": 0.01}):
        assert excel_model_export.unsupported_features(dict(growing, **extra)), extra
    assert excel_model_export.unsupported_features(growing) == []
