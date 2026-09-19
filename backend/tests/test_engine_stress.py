"""Stressed but schema-valid deals must compute (or fail with a typed 4xx),
never raise a 500. Long holds at high vacancy and rates used to overflow
the IRR solver and take down compute, sweeps, tornado and exports."""

import itertools
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import compute_cache

_FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    data = json.loads((_FIXTURES / name).read_text())
    data.pop("_comment", None)
    return data


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("fixture", ["analytic_acquisition.json", "analytic_development.json"])
def test_stressed_deals_never_500(client, fixture):
    base = _load(fixture)
    for hold, vacancy, rate in itertools.product([1, 25, 30], [0.0, 0.8, 0.99], [0.0, 0.25]):
        compute_cache.clear()
        values = dict(base, holdPeriodYears=hold, vacancyPct=vacancy, interestRate=rate)
        response = client.post("/api/compute", json={"values": values})
        assert response.status_code < 500, (hold, vacancy, rate, response.text[:200])


def test_sweep_through_stressed_cells_completes(client):
    # One unsolvable cell used to fail the whole sweep.
    base = dict(_load("analytic_acquisition.json"), holdPeriodYears=25, ioMonths=0)
    response = client.post(
        "/api/sensitivity",
        json={
            "mode": "native",
            "baseValues": base,
            "drivers": [
                {"fieldId": "vacancyPct", "values": [0.1, 0.3, 0.8]},
                {"fieldId": "interestRate", "values": [0.06, 0.15, 0.2]},
            ],
            "outputFieldIds": ["leveredIrr", "unleveredIrr"],
        },
    )
    assert response.status_code == 200, response.text[:300]
    assert len(response.json()["points"]) == 9
