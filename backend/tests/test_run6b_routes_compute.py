"""Run 6b: HTTP coverage for the scenario direct/delete/monte-carlo routes,
the compute Monte Carlo job + goal-seek endpoints, and the deal IC deck
download. Everything runs on the closed-form analytic acquisition fixture."""

import json
import time
from pathlib import Path

import pytest

from app.services import monte_carlo
from app.services.proforma import engine

FIXTURES = Path(__file__).parent / "fixtures"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def analytic(**overrides) -> dict:
    deal = json.loads((FIXTURES / "analytic_acquisition.json").read_text())
    deal.update(overrides)
    return deal


def _driver(path="exitCapRatePct", **params):
    return {"inputPath": path, "distribution": "uniform",
            "params": params or {"min": 0.07, "max": 0.09}}


# ------------------------------------------------------------------ scenarios


def test_get_and_delete_scenario_direct(client):
    created = client.post(
        "/api/scenarios",
        json={"scenarioName": "QS", "kind": "quickscreen", "inputs": {"x": 1}},
    )
    assert created.status_code == 200, created.text
    scenario = created.json()

    fetched = client.get(f"/api/scenarios/{scenario['id']}")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["scenarioName"] == "QS" and body["kind"] == "quickscreen"
    assert body["inputs"] == {"x": 1}
    assert body["monteCarlo"] is None and body["sensitivity"] is None
    assert client.get("/api/scenarios/nope").status_code == 404

    assert client.delete(f"/api/scenarios/{scenario['id']}").json() == {"deleted": True}
    assert client.get(f"/api/scenarios/{scenario['id']}").status_code == 404
    assert client.delete(f"/api/scenarios/{scenario['id']}").status_code == 404
    assert client.get("/api/scenarios").json() == []


def test_save_monte_carlo_on_scenario(client):
    scenario = client.post(
        "/api/scenarios",
        json={"scenarioName": "Full", "kind": "full", "inputs": analytic()},
    ).json()
    run = monte_carlo.run_simulation(
        analytic(), [_driver()], n=12, seed=321, hurdle_irr=0.08
    )
    saved = client.put(f"/api/scenarios/{scenario['id']}/monte-carlo", json={"monteCarlo": run})
    assert saved.status_code == 200, saved.text
    stored = saved.json()["monteCarlo"]
    assert stored["seed"] == 321
    assert stored["successfulRuns"] == 12
    assert stored["leveredIrr"]["p50"] == pytest.approx(run["leveredIrr"]["p50"])
    # Round-trips through the direct GET.
    assert client.get(f"/api/scenarios/{scenario['id']}").json()["monteCarlo"]["seed"] == 321

    assert client.put("/api/scenarios/nope/monte-carlo", json={"monteCarlo": run}).status_code == 404
    assert client.put(
        f"/api/scenarios/{scenario['id']}/monte-carlo", json={"wrongKey": {}}
    ).status_code == 422


# -------------------------------------------------------------------- compute


def test_monte_carlo_job_starts_and_polls_to_done(client):
    started = client.post(
        "/api/compute/monte-carlo",
        json={"values": analytic(), "drivers": [_driver()], "n": 10, "seed": 5},
    )
    assert started.status_code == 200, started.text
    job_id = started.json()["jobId"]
    assert started.json()["n"] == 10

    deadline = time.time() + 30
    status = client.get(f"/api/compute/monte-carlo/{job_id}").json()
    while status["status"] == "running" and time.time() < deadline:
        time.sleep(0.05)
        status = client.get(f"/api/compute/monte-carlo/{job_id}").json()
    assert status["status"] == "done", status
    assert status["completed"] == 10 and status["n"] == 10
    result = status["result"]
    assert result["seed"] == 5 and result["successfulRuns"] == 10
    assert result["probIrrNegative"] == 0  # 7-9% exit caps can't sink this deal
    # Seeded: the job reproduces a direct in-process run bit-for-bit.
    direct = monte_carlo.run_simulation(analytic(), [_driver()], n=10, seed=5, hurdle_irr=0.08)
    assert result["leveredIrr"] == direct["leveredIrr"]


def test_monte_carlo_validation_is_synchronous_and_unknown_job_404s(client):
    bad = client.post(
        "/api/compute/monte-carlo",
        json={"values": analytic(), "drivers": [_driver(path="notAField")], "n": 5, "seed": 1},
    )
    assert bad.status_code == 400
    too_many = client.post(
        "/api/compute/monte-carlo",
        json={"values": analytic(), "drivers": [_driver()], "n": monte_carlo.MAX_RUNS + 1},
    )
    assert too_many.status_code == 400
    assert client.get("/api/compute/monte-carlo/no-such-job").status_code == 404
    assert client.post("/api/compute/monte-carlo", json={"values": {}}).status_code == 422


def test_goal_seek_inputs_lists_numeric_schema_fields(client):
    response = client.get("/api/compute/goal-seek/inputs")
    assert response.status_code == 200
    rows = response.json()
    by_id = {row["id"]: row for row in rows}
    assert "purchasePrice" in by_id and "exitCapRatePct" in by_id
    assert "dealName" not in by_id  # text fields aren't solvable
    assert all(set(row) == {"id", "label", "type"} for row in rows)


def test_goal_seek_happy_path_and_400(client):
    target_irr = engine.compute(analytic())["outputs"]["leveredIrr"]
    response = client.post(
        "/api/compute/goal-seek",
        json={
            "values": analytic(purchasePrice=1_100_000), "targetInput": "purchasePrice",
            "outputMetric": "leveredIrr", "targetValue": target_irr,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["solvedValue"] == pytest.approx(1_000_000, rel=0.01)
    assert body["achievedMetric"] == pytest.approx(target_irr, abs=2e-5)

    bad_input = client.post(
        "/api/compute/goal-seek",
        json={
            "values": analytic(), "targetInput": "dealName",
            "outputMetric": "leveredIrr", "targetValue": 0.1,
        },
    )
    assert bad_input.status_code == 400
    bad_metric = client.post(
        "/api/compute/goal-seek",
        json={
            "values": analytic(), "targetInput": "purchasePrice",
            "outputMetric": "notAMetric", "targetValue": 0.1,
        },
    )
    assert bad_metric.status_code == 400
    assert client.post("/api/compute/goal-seek", json={"values": {}}).status_code == 422


# -------------------------------------------------------------------- IC deck


def test_ic_deck_download_for_computable_deal(client):
    deal = client.post("/api/deals", json={"name": "Deck Deal", "inputs": analytic()}).json()
    response = client.get(f"/api/deals/{deal['id']}/ic-deck.pptx")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith(PPTX)
    assert 'filename="Deck Deal-ic-deck.pptx"' in response.headers["content-disposition"]
    assert response.content[:2] == b"PK"
    skipped = set(filter(None, response.headers["x-deck-skipped"].split(",")))
    # No market/address on the fixture and no saved runs -> those slides skip.
    assert {"market", "sensitivity"} <= skipped


def test_ic_deck_uncomputable_deal_is_422_and_unknown_404(client):
    deal = client.post("/api/deals", json={"name": "Empty", "inputs": {}}).json()
    response = client.get(f"/api/deals/{deal['id']}/ic-deck.pptx")
    assert response.status_code == 422
    assert "missing inputs" in response.json()["detail"]
    assert client.get("/api/deals/nope/ic-deck.pptx").status_code == 404

    # A scenario id from another deal is rejected rather than silently used.
    other = client.post("/api/deals", json={"name": "Other", "inputs": analytic()}).json()
    scenario = client.post(
        "/api/scenarios",
        json={"scenarioName": "S", "kind": "full", "dealId": other["id"], "inputs": analytic()},
    ).json()
    computable = client.post("/api/deals", json={"name": "Mine", "inputs": analytic()}).json()
    assert client.get(
        f"/api/deals/{computable['id']}/ic-deck.pptx", params={"scenario_id": scenario["id"]}
    ).status_code == 404
