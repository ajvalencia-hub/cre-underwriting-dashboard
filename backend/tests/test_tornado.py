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


def test_cost_driver_label_names_the_field_actually_perturbed(analytic, development):
    """Type-aware label: the merged 'Hard costs / purchase price' never ships
    to the UI — acquisitions say Purchase price, developments Hard costs."""
    acq_bars = tornado_service.run_tornado(analytic, "leveredIrr")["bars"]
    assert next(b for b in acq_bars if b["key"] == "cost")["label"] == "Purchase price"
    dev_bars = tornado_service.run_tornado(development, "leveredIrr")["bars"]
    assert next(b for b in dev_bars if b["key"] == "cost")["label"] == "Hard costs"


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


REG_FIXTURES = Path(__file__).parent / "regression" / "fixtures"


def _bars(values: dict) -> dict:
    return {b["key"]: b for b in tornado_service.run_tornado(values, "leveredIrr")["bars"]}


def test_live_drivers_are_not_inert(analytic):
    """Flat-expense, GPR-driven, fixed-rate acquisition: every driver moves
    the deal — no inert flags, no reasons."""
    bars = _bars(analytic)
    assert all(b["inert"] is False for b in bars.values())
    assert all("reason" not in b for b in bars.values())


def test_opex_driver_is_inert_in_expense_detail_mode():
    rollover = json.loads((REG_FIXTURES / "commercial_rollover.json").read_text())
    bar = _bars(rollover)["opex"]
    assert bar["inert"] is True
    assert "opexLineItems" in bar["reason"]
    assert bar["impact"] == 0.0  # the computed swing corroborates the rule
    # The same deal with its lines removed (flat fields read) is live again.
    flat = {**rollover, "opexLineItems": [], "realEstateTaxes": 50_000}
    assert _bars(flat)["opex"]["inert"] is False


def test_rent_and_vacancy_drivers_are_inert_on_a_pure_lease_deal():
    rollover = json.loads((REG_FIXTURES / "commercial_rollover.json").read_text())
    bars = _bars(rollover)
    assert bars["rent"]["inert"] is True
    assert "rent roll" in bars["rent"]["reason"]
    assert bars["rent"]["impact"] == 0.0
    assert bars["vacancy"]["inert"] is True
    assert "downtime" in bars["vacancy"]["reason"]
    assert bars["vacancy"]["impact"] == 0.0
    # A mixed deal with a unit mix scales the residential rents — live.
    mixed = json.loads((REG_FIXTURES / "mixed_use.json").read_text())
    assert _bars(mixed)["rent"]["inert"] is False


def test_rate_driver_is_inert_in_floating_mode():
    feature_on = json.loads((REG_FIXTURES / "feature_on_value_add.json").read_text())
    bar = _bars(feature_on)["rate"]
    assert bar["inert"] is True
    assert "interestRate" in bar["reason"]
    assert bar["impact"] == 0.0
    assert _bars({**feature_on, "rateMode": "fixed"})["rate"]["inert"] is False


def test_exit_cap_driver_is_inert_when_both_component_caps_price_the_exit():
    mixed = json.loads((REG_FIXTURES / "mixed_use.json").read_text())
    bar = _bars(mixed)["exitCap"]
    assert bar["inert"] is True
    assert "component exit caps" in bar["reason"]
    assert bar["impact"] == 0.0
    single_cap = {**mixed, "commercialExitCapPct": None}
    assert _bars(single_cap)["exitCap"]["inert"] is False


def test_endpoint_and_bad_metric(analytic):
    client = TestClient(app)
    ok = client.post("/api/compute/tornado", json={"values": analytic, "metric": "leveredIrr"})
    assert ok.status_code == 200
    assert len(ok.json()["bars"]) == 6

    bad = client.post("/api/compute/tornado", json={"values": analytic, "metric": "nonsense"})
    assert bad.status_code == 400

    insufficient = client.post("/api/compute/tornado", json={"values": {"dealType": "acquisition"}})
    assert insufficient.status_code == 422
