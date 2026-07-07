"""K0: goal-seek endpoint — bisection over one input field against one output
metric, calling the pure engine.compute repeatedly. No engine math changes;
this only orchestrates the existing pure function in a loop."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import compute_solver
from app.services.proforma import engine

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def analytic() -> dict:
    return json.loads((FIXTURES / "analytic_acquisition.json").read_text())


def test_solve_hand_calculated_exit_cap(analytic):
    # Fixture is hand-derived: at exitCapRatePct=0.08, leveredIrr = 11.5718%
    # (see analytic_acquisition.json's _comment). Solve backwards for the
    # exit cap that hits that exact IRR and expect to land back on 0.08.
    target = engine.compute(analytic)["outputs"]["leveredIrr"]
    result = compute_solver.solve(
        analytic,
        target_field="exitCapRatePct",
        target_metric="leveredIrr",
        target_value=target,
        lower_bound=0.05,
        upper_bound=0.12,
        tolerance=1e-7,
    )
    assert result["fieldValue"] == pytest.approx(0.08, abs=1e-4)
    assert result["metricValue"] == pytest.approx(target, abs=1e-6)

    # solved value actually reproduces the target when plugged back in
    trial = {**analytic, "exitCapRatePct": result["fieldValue"]}
    assert engine.compute(trial)["outputs"]["leveredIrr"] == pytest.approx(target, abs=1e-6)


def test_solve_exact_bound_short_circuits(analytic):
    target = engine.compute(analytic)["outputs"]["leveredIrr"]
    result = compute_solver.solve(
        analytic,
        target_field="exitCapRatePct",
        target_metric="leveredIrr",
        target_value=target,
        lower_bound=0.08,
        upper_bound=0.12,
        tolerance=1e-4,
    )
    assert result["fieldValue"] == pytest.approx(0.08, abs=1e-6)
    assert result["iterations"] == 0


def test_solve_out_of_range_raises_typed_error(analytic):
    # leveredIrr never reaches 100% across a sane exit-cap range -> no sign
    # change -> must fail cleanly, not crash or silently return garbage.
    with pytest.raises(compute_solver.SolveOutOfRangeError):
        compute_solver.solve(
            analytic,
            target_field="exitCapRatePct",
            target_metric="leveredIrr",
            target_value=1.0,
            lower_bound=0.05,
            upper_bound=0.12,
        )


def test_solve_invalid_bounds_raises_value_error(analytic):
    with pytest.raises(ValueError):
        compute_solver.solve(
            analytic,
            target_field="exitCapRatePct",
            target_metric="leveredIrr",
            target_value=0.1,
            lower_bound=0.12,
            upper_bound=0.05,
        )


def test_solve_unknown_metric_raises_value_error(analytic):
    with pytest.raises(ValueError):
        compute_solver.solve(
            analytic,
            target_field="exitCapRatePct",
            target_metric="nonsenseMetric",
            target_value=0.1,
            lower_bound=0.05,
            upper_bound=0.12,
        )


def test_solve_endpoint_happy_path(analytic):
    client = TestClient(app)
    target = engine.compute(analytic)["outputs"]["leveredIrr"]
    resp = client.post(
        "/api/compute/solve",
        json={
            "values": analytic,
            "targetField": "exitCapRatePct",
            "targetMetric": "leveredIrr",
            "targetValue": target,
            "lowerBound": 0.05,
            "upperBound": 0.12,
            "tolerance": 1e-7,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["fieldValue"] == pytest.approx(0.08, abs=1e-4)


def test_solve_endpoint_out_of_range_is_400(analytic):
    client = TestClient(app)
    resp = client.post(
        "/api/compute/solve",
        json={
            "values": analytic,
            "targetField": "exitCapRatePct",
            "targetMetric": "leveredIrr",
            "targetValue": 1.0,
            "lowerBound": 0.05,
            "upperBound": 0.12,
        },
    )
    assert resp.status_code == 400


def test_solve_endpoint_insufficient_inputs_is_422():
    client = TestClient(app)
    resp = client.post(
        "/api/compute/solve",
        json={
            "values": {"dealType": "acquisition"},
            "targetField": "exitCapRatePct",
            "targetMetric": "leveredIrr",
            "targetValue": 0.1,
            "lowerBound": 0.05,
            "upperBound": 0.12,
        },
    )
    assert resp.status_code == 422
    assert "missing" in resp.json()
