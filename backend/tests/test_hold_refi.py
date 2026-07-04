"""G6: hold-period sweep and refi-vs-sale — internal consistency with the
base compute, refi proceeds arithmetic, and degenerate-case warnings."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.proforma import engine, hold

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def analytic() -> dict:
    return json.loads((FIXTURES / "analytic_acquisition.json").read_text())


@pytest.fixture
def development() -> dict:
    return json.loads((FIXTURES / "analytic_development.json").read_text())


def test_modeled_hold_row_equals_base_compute(analytic):
    sweep = hold.hold_sweep(analytic)
    base = engine.compute(analytic)["outputs"]
    modeled = next(r for r in sweep["rows"] if r["holdYear"] == analytic["holdPeriodYears"])
    assert modeled["leveredIrr"] == pytest.approx(base["leveredIrr"], abs=1e-12)
    assert modeled["equityMultiple"] == pytest.approx(base["equityMultiple"], abs=1e-12)
    assert modeled["netProceeds"] == pytest.approx(base["netSaleProceeds"], abs=1e-9)


def test_acquisition_sweeps_every_year_from_one(analytic):
    sweep = hold.hold_sweep(analytic)
    assert [r["holdYear"] for r in sweep["rows"]] == list(
        range(1, int(analytic["holdPeriodYears"]) + 1)
    )


def test_development_sweeps_start_after_stabilization(development):
    # Stabilization at month 31 -> year 3 -> sweep starts at year 4.
    sweep = hold.hold_sweep(development)
    assert [r["holdYear"] for r in sweep["rows"]] == [4, 5, 6, 7]
    assert sweep["modeledHoldYears"] == 7


def test_never_stabilizing_deal_warns_instead_of_crashing(development):
    stuck = {**development, "holdPeriodYears": 2}  # construction alone is 18 months
    sweep = hold.hold_sweep(stuck)
    assert sweep["rows"] == []
    assert any("stabilizes" in w for w in sweep["warnings"])
    fork = hold.refi_vs_sale({**development, "holdPeriodYears": 1})
    assert fork["holdThroughRefi"] is None
    assert any("never stabilizes" in w for w in fork["warnings"])


def test_refi_proceeds_arithmetic(development):
    """Cash-out = sized refi loan - construction payoff; costs = refiCostsPct
    x new loan. All three are reported and reconcile against the statement."""
    inputs = {**development, "refiCostsPct": 0.01, "refiRateSpreadPct": 0.005}
    fork = hold.refi_vs_sale(inputs)
    refi = fork["holdThroughRefi"]
    assert refi is not None

    result = engine.compute(inputs)
    statement = result["statement"]
    takeout = statement["stabilizationMonth"]
    # The construction balance retired at takeout is the carry balance at the
    # END of the month before takeout (the takeout month itself is already on
    # the perm schedule).
    payoff = statement["loanBalance"][takeout - 1]
    assert refi["cashOutProceeds"] == pytest.approx(refi["refiLoan"] - payoff, rel=1e-9)
    assert refi["refiCosts"] == pytest.approx(refi["refiLoan"] * 0.01, rel=1e-9)
    # the refi levered outcome matches the base modeled compute exactly
    assert refi["leveredIrr"] == pytest.approx(result["outputs"]["leveredIrr"], abs=1e-12)


def test_refi_spread_prices_the_perm_loan(development):
    """+100bps refi spread shrinks the DSCR-constrained proceeds (bigger
    constant) and raises the perm interest paid. This deal is DSCR-governed,
    so its realized min DSCR stays pinned at the constraint BY CONSTRUCTION —
    the sizing absorbs the rate move, which is exactly the point."""
    base = engine.compute(development)
    spread = engine.compute({**development, "refiRateSpreadPct": 0.01})
    assert spread["debt"]["candidates"]["dscr"] < base["debt"]["candidates"]["dscr"]
    assert spread["debt"]["loanAmount"] < base["debt"]["loanAmount"]
    takeout = base["statement"]["stabilizationMonth"]
    assert (
        spread["statement"]["interest"][takeout + 2]
        > base["statement"]["interest"][takeout + 2]
    )
    # defaults preserve Run-1 behavior exactly
    zero = engine.compute({**development, "refiRateSpreadPct": 0, "refiCostsPct": 0})
    assert zero["outputs"]["leveredIrr"] == pytest.approx(base["outputs"]["leveredIrr"], abs=1e-12)


def test_endpoint(analytic):
    client = TestClient(app)
    resp = client.post("/api/compute/hold-sweep", json={"values": analytic})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["sweep"]["rows"]) == int(analytic["holdPeriodYears"])
    # a day-one-stabilized acquisition has no refi fork
    assert body["refiVsSale"]["saleAtStabilization"] is None

    insufficient = client.post("/api/compute/hold-sweep", json={"values": {"dealType": "acquisition"}})
    assert insufficient.status_code in (200, 422)  # sweep warns per-year or 422s upfront
