"""G3: native sensitivity — the sweep reproduces individual engine calls,
behaves monotonically where economics demand it, routes by mode, and saved
runs round-trip on the scenario."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.services import sensitivity_service
from app.services.proforma import engine

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def analytic() -> dict:
    return json.loads((FIXTURES / "analytic_acquisition.json").read_text())


def test_native_sweep_reproduces_individual_engine_calls(analytic):
    drivers = [
        {"fieldId": "exitCapRatePct", "values": [0.06, 0.07, 0.08]},
        {"fieldId": "rentGrowthPct", "values": [0.02, 0.04]},
    ]
    outcome = sensitivity_service.run_native_sensitivity(
        analytic, drivers, ["leveredIrr", "terminalValue"]
    )
    assert len(outcome["points"]) == 6
    for point in outcome["points"]:
        expected = engine.compute({**analytic, **point["driverValues"]})["outputs"]
        assert point["outputs"]["leveredIrr"] == pytest.approx(expected["leveredIrr"], abs=1e-12)
        assert point["outputs"]["terminalValue"] == pytest.approx(
            expected["terminalValue"], abs=1e-9
        )
        # only the requested outputs come back
        assert set(point["outputs"].keys()) == {"leveredIrr", "terminalValue"}


def test_monotonicity_higher_exit_cap_lower_terminal_value(analytic):
    caps = [0.05, 0.06, 0.07, 0.08, 0.09]
    outcome = sensitivity_service.run_native_sensitivity(
        analytic, [{"fieldId": "exitCapRatePct", "values": caps}], ["terminalValue", "leveredIrr"]
    )
    terminal_values = [p["outputs"]["terminalValue"] for p in outcome["points"]]
    assert terminal_values == sorted(terminal_values, reverse=True)
    levered = [p["outputs"]["leveredIrr"] for p in outcome["points"]]
    assert levered == sorted(levered, reverse=True)


def test_uncomputable_grid_point_warns_instead_of_failing(analytic):
    # exitCapRatePct 0 makes the whole compute insufficient — that point warns.
    outcome = sensitivity_service.run_native_sensitivity(
        analytic, [{"fieldId": "exitCapRatePct", "values": [0.0, 0.06]}], ["leveredIrr"]
    )
    bad, good = outcome["points"]
    assert bad["outputs"] == {} and any("not computable" in w for w in bad["warnings"])
    assert "leveredIrr" in good["outputs"]


# ------------------------------------------------------------------ routing

@pytest.fixture
def client():
    sql_engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(sql_engine)
    TestSession = sessionmaker(bind=sql_engine)

    def _override():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    yield TestClient(app)
    app.dependency_overrides.pop(get_db)
    sql_engine.dispose()


def test_native_mode_needs_no_template(client, analytic):
    resp = client.post(
        "/api/sensitivity",
        json={
            "mode": "native",
            "baseValues": analytic,
            "drivers": [{"fieldId": "exitCapRatePct", "values": [0.06, 0.07]}],
            "outputFieldIds": ["leveredIrr"],
        },
    )
    assert resp.status_code == 200
    assert len(resp.json()["points"]) == 2


def test_template_mode_still_requires_template(client, analytic):
    resp = client.post(
        "/api/sensitivity",
        json={
            "mode": "template",
            "baseValues": analytic,
            "drivers": [{"fieldId": "exitCapRatePct", "values": [0.06]}],
            "outputFieldIds": ["leveredIrr"],
        },
    )
    assert resp.status_code == 400
    assert "Template mode requires" in resp.json()["detail"]


def test_native_grid_cap_enforced(client, analytic):
    resp = client.post(
        "/api/sensitivity",
        json={
            "mode": "native",
            "baseValues": analytic,
            "drivers": [
                {"fieldId": "exitCapRatePct", "values": [0.05 + i * 0.001 for i in range(26)]},
                {"fieldId": "rentGrowthPct", "values": [0.01 * i for i in range(26)]},
            ],
            "outputFieldIds": ["leveredIrr"],
        },
    )
    assert resp.status_code == 400
    assert "Grid too large" in resp.json()["detail"]


def test_saved_run_round_trips_on_the_scenario(client):
    created = client.post(
        "/api/scenarios",
        json={"scenarioName": "QS", "kind": "quickscreen", "inputs": {"x": 1}},
    ).json()
    saved_run = {
        "description": "Levered IRR — exit cap × rent growth, native engine",
        "header": ["cap \\ growth", "2%", "4%"],
        "rows": [["6.00%", "12.1%", "13.0%"]],
        "run": {"mode": "native", "drivers": [], "outputFieldIds": ["leveredIrr"], "points": []},
    }
    resp = client.put(f"/api/scenarios/{created['id']}/sensitivity", json={"sensitivity": saved_run})
    assert resp.status_code == 200
    assert resp.json()["sensitivity"]["description"].startswith("Levered IRR")

    fetched = client.get(f"/api/scenarios/{created['id']}").json()
    assert fetched["sensitivity"] == saved_run
