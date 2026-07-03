"""F2: the engine against the fully hand-calculated analytic fixture (see the
_comment block in fixtures/analytic_acquisition.json for every derivation),
plus degenerate cases and the /api/compute wire-up.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.proforma import engine

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def analytic() -> dict:
    return json.loads((FIXTURES / "analytic_acquisition.json").read_text())


def test_analytic_acquisition_all_hand_calculated_outputs(analytic):
    result = engine.compute(analytic)
    out = result["outputs"]

    # IRRs to +-1bp against the closed-form derivations.
    assert out["unleveredIrr"] == pytest.approx((1 + 0.06 / 9) ** 12 - 1, abs=1e-4)  # 8.29995%
    assert out["leveredIrr"] == pytest.approx(1.0091666667**12 - 1, abs=1e-4)  # 11.5718%

    assert out["equityMultiple"] == pytest.approx(1.55, abs=1e-6)
    assert out["moic"] == pytest.approx(1.55, abs=1e-6)
    assert out["annualizedReturn"] == pytest.approx(1.55 ** (1 / 5) - 1, abs=1e-9)
    assert out["paybackPeriodYears"] == pytest.approx(4.955, abs=0.01)

    assert out["cashOnCashYear1"] == pytest.approx(0.11, abs=1e-6)
    assert out["avgCashOnCash"] == pytest.approx(0.11, abs=1e-6)
    assert out["stabilizedCashOnCash"] == pytest.approx(0.11, abs=1e-6)

    assert out["terminalValue"] == pytest.approx(1_000_000, abs=1)
    assert out["netSaleProceeds"] == pytest.approx(400_000, abs=1)
    assert out["totalProfit"] == pytest.approx(220_000, abs=1)
    assert out["npv"] == pytest.approx(22_677, abs=25)
    assert out["profitabilityIndex"] == pytest.approx(1.0567, abs=1e-3)

    assert out["goingInCapRate"] == pytest.approx(0.08, abs=1e-9)
    assert out["yieldOnCost"] == pytest.approx(0.08, abs=1e-9)
    assert out["developmentSpreadBps"] == pytest.approx(0.0, abs=1e-9)

    assert out["minDscr"] == pytest.approx(80_000 / 36_000, abs=1e-6)
    assert out["avgDscr"] == pytest.approx(80_000 / 36_000, abs=1e-6)
    assert out["debtYield"] == pytest.approx(80_000 / 600_000, abs=1e-9)
    assert out["ltv"] == pytest.approx(0.6, abs=1e-9)
    assert out["ltc"] == pytest.approx(0.6, abs=1e-9)
    assert out["loanConstant"] == pytest.approx(0.06, abs=1e-9)
    assert out["breakEvenRatio"] == pytest.approx(0.46, abs=1e-6)
    assert out["breakEvenOccupancy"] == pytest.approx(0.46, abs=1e-6)
    assert out["interestCoverageRatio"] == pytest.approx(80_000 / 36_000, abs=1e-4)

    # No promote tiers: LP and GP ride pro-rata with the deal.
    assert out["lpIrr"] == pytest.approx(out["leveredIrr"], abs=1e-6)
    assert out["gpIrr"] == pytest.approx(out["leveredIrr"], abs=1e-6)
    assert out["lpEquityMultiple"] == pytest.approx(1.55, abs=1e-6)


def test_zero_leverage_collapses_levered_to_unlevered(analytic):
    inputs = {**analytic, "loanAmount": 0, "ltvOrLtc": 0}
    out = engine.compute(inputs)["outputs"]
    assert out["leveredIrr"] == pytest.approx(out["unleveredIrr"], abs=1e-9)
    assert "minDscr" not in out
    assert "debtYield" not in out


def test_one_month_hold_does_not_crash(analytic):
    inputs = {**analytic, "holdPeriodYears": 1 / 12, "ioMonths": 1}
    result = engine.compute(inputs)
    assert result["outputs"]["terminalValue"] == pytest.approx(1_000_000, abs=1)


def test_development_deal_with_lease_up_past_exit_warns(analytic):
    inputs = {
        **analytic,
        "dealType": "development",
        "landCost": 1_000_000,
        "hardCosts": 8_000_000,
        "softCosts": 1_000_000,
        "contingencyPct": 0.05,
        "developerFeePct": 0.04,
        "constructionMonths": 6,
        "leaseUpMonths": 120,
        "holdPeriodYears": 3,
    }
    result = engine.compute(inputs)
    assert any("sold before stabilizing" in w for w in result["warnings"])


def test_development_yield_on_cost_consistency(analytic):
    inputs = {
        **analytic,
        "dealType": "development",
        "landCost": 1_000_000,
        "hardCosts": 8_000_000,
        "softCosts": 1_000_000,
        "contingencyPct": 0.05,
        "developerFeePct": 0.04,
        "constructionMonths": 12,
        "leaseUpMonths": 6,
        "grossPotentialRent": 1_200_000,
        "holdPeriodYears": 5,
    }
    out = engine.compute(inputs)["outputs"]
    # Stabilized NOI = 1.2M x 0.9 - 10k = 1,070,000; TDC >= 10.828M (plus
    # capitalized interest), so YoC < 1,070,000 / 10,828,000 and > NOI/(TDC*1.1).
    assert out["yieldOnCost"] < 1_070_000 / 10_828_000
    assert out["yieldOnCost"] > 1_070_000 / (10_828_000 * 1.10)
    assert out["goingInCapRate"] == pytest.approx(out["yieldOnCost"], abs=1e-12)


def test_insufficient_inputs_names_every_missing_field():
    with pytest.raises(engine.InsufficientInputsError) as exc:
        engine.compute({"dealType": "acquisition", "holdPeriodYears": 5})
    missing = exc.value.missing
    assert "exitCapRatePct" in missing
    assert "purchasePrice" in missing
    assert any("grossPotentialRent" in m for m in missing)


def test_compute_endpoint_round_trip(analytic):
    client = TestClient(app)
    response = client.post("/api/compute", json={"values": analytic})
    assert response.status_code == 200
    body = response.json()
    assert body["outputs"]["equityMultiple"] == pytest.approx(1.55, abs=1e-6)
    assert isinstance(body["warnings"], list)


def test_compute_endpoint_422_names_missing_fields():
    client = TestClient(app)
    response = client.post("/api/compute", json={"values": {"dealType": "acquisition"}})
    assert response.status_code == 422
    assert "purchasePrice" in response.json()["missing"]
