"""G2: the period-level statement — response shape, per-period accounting
identities (which hold by construction and must stay that way), and annual
aggregation equaling the sum of months."""

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


@pytest.fixture
def development() -> dict:
    return json.loads((FIXTURES / "analytic_development.json").read_text())


_SERIES_KEYS = [
    "gpr", "vacancyLoss", "creditLoss", "otherIncome", "egi", "managementFee",
    "opexTotal", "noi", "occupancy", "costs", "loanFees", "equityFunded",
    "debtDraws", "interest", "principal", "debtService", "loanBalance",
    "saleProceedsNet", "saleProceedsGross", "unlevered", "levered",
    "lpDistributions", "gpDistributions",
]


def _assert_identities(statement: dict) -> None:
    n = len(statement["months"])
    for key in _SERIES_KEYS:
        assert len(statement[key]) == n, f"{key} length"
    for category, vec in statement["fixedOpexByCategory"].items():
        assert len(vec) == n, f"fixedOpexByCategory[{category}] length"

    for m in range(n):
        egi = (
            statement["gpr"][m]
            - statement["vacancyLoss"][m]
            - statement["creditLoss"][m]
            + statement["otherIncome"][m]
        )
        assert statement["egi"][m] == pytest.approx(egi, abs=1e-6), f"EGI identity @ {m}"

        opex = statement["managementFee"][m] + sum(
            vec[m] for vec in statement["fixedOpexByCategory"].values()
        )
        assert statement["opexTotal"][m] == pytest.approx(opex, abs=1e-6), f"opex identity @ {m}"
        assert statement["noi"][m] == pytest.approx(
            statement["egi"][m] - statement["opexTotal"][m], abs=1e-6
        ), f"NOI identity @ {m}"

        levered = (
            statement["noi"][m]
            - statement["debtService"][m]
            + statement["debtDraws"][m]
            - statement["costs"][m]
            - statement["loanFees"][m]
            + statement["saleProceedsNet"][m]
        )
        assert statement["levered"][m] == pytest.approx(levered, abs=1e-6), f"levered tie @ {m}"


def test_acquisition_statement_identities(analytic):
    result = engine.compute(analytic)
    _assert_identities(result["statement"])


def test_development_statement_identities(development):
    result = engine.compute(development)
    _assert_identities(result["statement"])


def test_statement_totals_tie_to_scalar_outputs(analytic):
    """The statement is the engine's own vectors: total levered CF must equal
    the totalProfit output, and the exit-month sale row the netSaleProceeds."""
    result = engine.compute(analytic)
    statement = result["statement"]
    assert sum(statement["levered"]) == pytest.approx(result["outputs"]["totalProfit"], abs=1e-6)
    assert statement["saleProceedsNet"][statement["exitMonth"]] == pytest.approx(
        result["outputs"]["netSaleProceeds"], abs=1e-6
    )
    # LP + GP distributions account for every levered dollar.
    for m in statement["months"]:
        assert statement["lpDistributions"][m] + statement["gpDistributions"][m] == pytest.approx(
            statement["levered"][m], abs=1e-6
        )


def test_annual_aggregation_equals_sum_of_months(analytic):
    """Fiscal-year sums are pure presentation: any 12-month block's sum over
    a flow series equals the sum of its months (the frontend groups Year k =
    months 12(k-1)+1 .. 12k, Close separate)."""
    statement = engine.compute(analytic)["statement"]
    total_months = len(statement["months"]) - 1
    for series in ("noi", "levered", "egi", "debtService"):
        vec = statement[series]
        annual_sum = 0.0
        for start in range(1, total_months + 1, 12):
            annual_sum += sum(vec[start : min(start + 12, total_months + 1)])
        assert annual_sum + vec[0] == pytest.approx(sum(vec), abs=1e-9), series


def test_detail_flag_gates_the_statement(analytic):
    client = TestClient(app)
    lean = client.post("/api/compute", json={"values": analytic})
    assert lean.status_code == 200
    assert "statement" not in lean.json()

    detailed = client.post("/api/compute?detail=true", json={"values": analytic})
    assert detailed.status_code == 200
    statement = detailed.json()["statement"]
    assert statement["months"][0] == 0
    assert statement["phases"][0] == "close"
    assert len(statement["levered"]) == len(statement["months"])


def test_development_phases_labelled(development):
    statement = engine.compute(development)["statement"]
    assert statement["phases"][0] == "close"
    construction_months = statement["constructionMonths"]
    if construction_months:
        assert statement["phases"][1] == "construction"
        assert "stabilized" in statement["phases"]
