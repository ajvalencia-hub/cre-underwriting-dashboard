"""Run 6 analysis-caller fixes ported onto later-items (G2): P1 — the hold
sweep, refi fork, tornado, native sensitivity and goal-seek skip the H3
insurance-stress sub-computes (only the base compute's debt card reads
them) — and tornado inert/reason flags, including the target's hotel and
build-to-sell shapes."""

import json
from pathlib import Path

import pytest

from app.services import compute_cache, goal_seek, sensitivity_service, tornado_service
from app.services.proforma import engine, hold

FIXTURES = Path(__file__).parent / "fixtures"
REG_FIXTURES = Path(__file__).parent / "regression" / "fixtures"


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


@pytest.fixture
def analytic() -> dict:
    return _load(FIXTURES / "analytic_acquisition.json")


@pytest.fixture
def rollover() -> dict:
    return _load(REG_FIXTURES / "commercial_rollover.json")


@pytest.fixture
def calls(monkeypatch):
    """Counts every engine.compute call (nested stress computes included —
    they call the module-level name) and records whether each skipped the
    stress sub-computes."""
    seen: list[bool] = []
    original = engine.compute

    def counting(inputs):
        seen.append(bool(inputs.get("_skipCategoricalStress")))
        return original(inputs)

    monkeypatch.setattr(engine, "compute", counting)
    compute_cache.clear()
    return seen


# ---------------------------------------------------------------------------
# P1
# ---------------------------------------------------------------------------
def test_p1_stress_is_live_on_the_fixture(rollover, calls):
    assert engine.compute(rollover)["debt"]["insuranceStress"]
    assert len(calls) == 3  # base + two bumped sub-computes


def test_p1_tornado_compute_count(rollover, calls):
    tornado_service.run_tornado(rollover, "leveredIrr")
    assert len(calls) == 2 * len(tornado_service.DRIVERS) + 1
    assert all(calls)


def test_p1_hold_sweep_and_refi_fork(rollover, calls):
    sweep = hold.hold_sweep(rollover)
    assert len(calls) == len(sweep["rows"]) and all(calls)
    calls.clear()
    dev = _load(FIXTURES / "analytic_development.json")
    hold.refi_vs_sale({**dev, "opexLineItems": rollover["opexLineItems"]})
    assert len(calls) == 2 and all(calls)


def test_p1_native_sensitivity(rollover, calls):
    sensitivity_service.run_native_sensitivity(
        rollover, [{"fieldId": "exitCapRatePct", "values": [0.065, 0.07]}], ["leveredIrr"]
    )
    assert len(calls) == 2 and all(calls)


def test_p1_goal_seek_points_skip_stress_and_cache_separately(rollover, calls):
    goal_seek.run_goal_seek(rollover, "purchasePrice", "leveredIrr", 0.10)
    assert calls and all(calls)
    # The flag is part of the compute-cache key: a full compute of the same
    # inputs is a miss, never a stress-less cached result.
    full = compute_cache.cached_compute(rollover)
    assert full["debt"]["insuranceStress"]


def test_p1_skipping_stress_changes_nothing_the_callers_read(rollover):
    full = engine.compute(rollover)
    lean = engine.compute({**rollover, "_skipCategoricalStress": True})
    assert lean["outputs"] == full["outputs"]
    assert lean["statement"] == full["statement"]
    assert lean["warnings"] == full["warnings"]
    assert {k: v for k, v in full["debt"].items() if k != "insuranceStress"} == lean["debt"]


# ---------------------------------------------------------------------------
# Tornado inert / reason
# ---------------------------------------------------------------------------
def _bars(values: dict) -> dict:
    return {b["key"]: b for b in tornado_service.run_tornado(values, "leveredIrr")["bars"]}


def test_live_drivers_are_not_inert(analytic):
    bars = _bars(analytic)
    assert all(b["inert"] is False and b["reason"] is None for b in bars.values())


def test_opex_rent_vacancy_inert_on_detail_mode_lease_deal(rollover):
    bars = _bars(rollover)
    assert bars["opex"]["inert"] and "opexLineItems" in bars["opex"]["reason"]
    assert bars["rent"]["inert"] and "rent roll" in bars["rent"]["reason"]
    assert bars["vacancy"]["inert"] and "downtime" in bars["vacancy"]["reason"]
    for key in ("opex", "rent", "vacancy"):
        assert bars[key]["impact"] == 0.0  # the computed swing corroborates
    assert not bars["exitCap"]["inert"]
    flat = {**rollover, "opexLineItems": [], "realEstateTaxes": 50_000}
    assert _bars(flat)["opex"]["inert"] is False


def test_rate_inert_in_floating_mode():
    feature_on = _load(REG_FIXTURES / "feature_on_value_add.json")
    bar = _bars(feature_on)["rate"]
    assert bar["inert"] and "interestRate" in bar["reason"] and bar["impact"] == 0.0
    assert _bars({**feature_on, "rateMode": "fixed", "interestRate": 0.065})["rate"]["inert"] is False


def test_exit_cap_inert_under_component_caps():
    mixed = _load(REG_FIXTURES / "mixed_use.json")
    bars = _bars(mixed)
    assert bars["exitCap"]["inert"] and "component exit caps" in bars["exitCap"]["reason"]
    assert bars["exitCap"]["impact"] == 0.0
    assert bars["rent"]["inert"] is False  # the unit mix is scaled
    assert _bars({**mixed, "commercialExitCapPct": None})["exitCap"]["inert"] is False


def test_hotel_rent_and_vacancy_inert(analytic):
    hotel = {**analytic, "propertyType": "hotel", "keys": 120, "adr": 180,
             "occupancyPct": 0.72, "grossPotentialRent": 0, "loanAmount": 0}
    bars = _bars(hotel)
    for key in ("rent", "vacancy"):
        assert bars[key]["inert"] and "hotel" in bars[key]["reason"].lower(), key
        assert bars[key]["impact"] == 0.0
    assert bars["exitCap"]["inert"] is False


def test_for_sale_drivers_inert():
    deal = {
        "dealType": "development", "propertyType": "townhouse", "isForSale": True,
        "landCost": 2_000_000, "hardCosts": 1_000_000, "homeCount": 40,
        "absorptionPerMonth": 3, "salePricePerHome": 450_000, "buildCostPerHome": 250_000,
        "homeBuildMonths": 6, "constructionMonths": 6, "ltvOrLtc": 0.6, "interestRate": 0.08,
        "vacancyPct": 0.05, "exitCapRatePct": 0.06, "grossPotentialRent": 1_000_000,
    }
    bars = _bars(deal)
    for key in ("rent", "vacancy", "opex", "exitCap"):
        assert bars[key]["inert"] and "build-to-sell" in bars[key]["reason"], key
        assert bars[key]["impact"] == 0.0, key
    assert bars["cost"]["inert"] is False and bars["rate"]["inert"] is False
