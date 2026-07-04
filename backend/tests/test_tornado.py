"""G4: tornado analysis — perturbation rules, ordering by impact, and the
endpoint wire-up."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import tornado_service
from app.services.proforma import engine

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def analytic() -> dict:
    return json.loads((FIXTURES / "analytic_acquisition.json").read_text())


@pytest.fixture
def development() -> dict:
    return json.loads((FIXTURES / "analytic_development.json").read_text())


def test_perturb_rules(analytic, development):
    up = tornado_service.perturb(analytic, "rent", +1)
    assert up["grossPotentialRent"] == pytest.approx(analytic["grossPotentialRent"] * 1.10)

    cap = tornado_service.perturb(analytic, "exitCap", -1)
    assert cap["exitCapRatePct"] == pytest.approx(analytic["exitCapRatePct"] - 0.005)

    cost_acq = tornado_service.perturb(analytic, "cost", +1)
    assert cost_acq["purchasePrice"] == pytest.approx(analytic["purchasePrice"] * 1.10)
    cost_dev = tornado_service.perturb(development, "cost", +1)
    assert cost_dev["hardCosts"] == pytest.approx(development["hardCosts"] * 1.10)

    vac = tornado_service.perturb(analytic, "vacancy", +1)
    assert vac["vacancyPct"] == pytest.approx(analytic["vacancyPct"] * 1.10)  # relative

    rate = tornado_service.perturb(analytic, "rate", +1)
    assert rate["interestRate"] == pytest.approx(analytic["interestRate"] + 0.005)

    opex = tornado_service.perturb(development, "opex", -1)
    assert opex["realEstateTaxes"] == pytest.approx(development["realEstateTaxes"] * 0.90)
    assert opex["managementFeePct"] == pytest.approx(development["managementFeePct"] * 0.90)

    # the original dict is never mutated
    assert analytic["grossPotentialRent"] != up["grossPotentialRent"]


def test_rent_perturbation_scales_unit_mix_when_present(analytic):
    values = {
        **analytic,
        "unitMix": [
            {"unitType": "1BR", "unitCount": 10, "inPlaceRent": 1000, "marketRent": 1100}
        ],
    }
    up = tornado_service.perturb(values, "rent", +1)
    assert up["unitMix"][0]["inPlaceRent"] == pytest.approx(1100)
    assert up["unitMix"][0]["marketRent"] == pytest.approx(1210)
    # the flat GPR field is left alone — unit mix is the GPR source
    assert up["grossPotentialRent"] == analytic["grossPotentialRent"]


def test_bars_sorted_by_impact_and_consistent_with_direct_computes(analytic):
    result = tornado_service.run_tornado(analytic, "leveredIrr")
    impacts = [b["impact"] for b in result["bars"]]
    assert impacts == sorted(impacts, reverse=True)
    assert {b["key"] for b in result["bars"]} == {
        "rent", "exitCap", "cost", "opex", "rate", "vacancy",
    }
    # spot-check one bar against a direct engine call
    rent_bar = next(b for b in result["bars"] if b["key"] == "rent")
    direct = engine.compute(tornado_service.perturb(analytic, "rent", +1))["outputs"]["leveredIrr"]
    assert rent_bar["high"] == pytest.approx(direct, abs=1e-12)
    # economics sanity: more rent -> higher levered IRR
    assert rent_bar["high"] > result["base"] > rent_bar["low"]


def test_endpoint_and_bad_metric(analytic):
    client = TestClient(app)
    ok = client.post("/api/compute/tornado", json={"values": analytic, "metric": "leveredIrr"})
    assert ok.status_code == 200
    assert len(ok.json()["bars"]) == 6

    bad = client.post("/api/compute/tornado", json={"values": analytic, "metric": "nonsense"})
    assert bad.status_code == 400

    insufficient = client.post("/api/compute/tornado", json={"values": {"dealType": "acquisition"}})
    assert insufficient.status_code == 422
