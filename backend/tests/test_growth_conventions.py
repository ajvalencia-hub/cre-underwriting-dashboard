"""Trended vs untrended yield on cost, and the growth-during-construction
option (roadmap #23). Development rents are flat through the build by
default (growth starts at delivery); the option trends them from close."""

import json
from pathlib import Path

import pytest

from app.services.proforma import engine

_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def dev():
    # 18-month build, 12-month lease-up, rents +3%/yr, expenses +2.5%/yr.
    data = json.loads((_FIXTURES / "analytic_development.json").read_text())
    data.pop("_comment", None)
    return data


def test_trended_yield_on_cost_is_the_first_stabilized_year_over_the_basis(dev):
    result = engine.compute(dev)
    stmt, outputs = result["statement"], result["outputs"]
    first = stmt["stabilizationMonth"]
    trended_noi = sum(stmt["noi"][first : first + 12])
    assert outputs["trendedYieldOnCost"] == pytest.approx(trended_noi / result["constructionLoan"]["totalCost"])
    # With growth, the stabilized year earns more than today's rents.
    assert outputs["trendedYieldOnCost"] > outputs["yieldOnCost"]


def test_growth_can_run_from_closing_instead_of_delivery(dev):
    off = engine.compute(dev)["statement"]
    on = engine.compute(dict(dev, growDuringConstruction=True))["statement"]
    delivery = 19  # first month after the 18-month build
    # By delivery, 18 months have passed: one annual step already applied.
    assert on["gpr"][delivery] / off["gpr"][delivery] == pytest.approx(1.03)
    assert engine.compute(dict(dev, growDuringConstruction=True))["outputs"]["leveredIrr"] > engine.compute(dev)["outputs"]["leveredIrr"]


def test_growth_option_is_off_by_default_and_ignored_for_acquisitions(dev):
    assert engine.compute(dict(dev, growDuringConstruction=False))["outputs"] == engine.compute(dev)["outputs"]
    acq = json.loads((_FIXTURES / "analytic_acquisition.json").read_text())
    assert engine.compute(dict(acq, growDuringConstruction=True))["outputs"] == engine.compute(acq)["outputs"]
