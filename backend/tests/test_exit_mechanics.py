"""Exit mechanics (roadmap #24): trailing vs forward NOI for the exit value,
and a prepayment cost on the loan repaid at sale."""

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

    assert excel_model_export.unsupported_features(dict(growing, exitNoiBasis="trailing"))
    assert excel_model_export.unsupported_features(growing) == []
    # Run 6 port: the prepayment cost is mirrored (exit payoff x (1 + pct));
    # parity cases export_prepayment_{acquisition,development} pin it.
    assert excel_model_export.unsupported_features(dict(growing, prepaymentPenaltyPct=0.01)) == []


def test_negative_exit_noi_floors_the_sale_price_at_zero():
    # Opex above income: exit NOI is negative and the capitalized value
    # would be a negative sale price (owner decision 2026-09-19: floor at 0).
    import json
    from pathlib import Path

    from app.services.proforma.engine import compute

    deal = json.loads((Path(__file__).parent / "fixtures" / "analytic_acquisition.json").read_text())
    deal.pop("_comment", None)
    deal["insurance"] = 80_001  # NOI = 90,000 EGI - 90,001 opex
    result = compute(deal)
    assert result["outputs"]["terminalValue"] == 0
    assert any("floored at $0" in w for w in result["warnings"])
