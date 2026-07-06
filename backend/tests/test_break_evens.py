"""J9: per-calendar-year operating break-evens on the statement vectors.

Analytic acquisition hand numbers (flat deal, every year identical):
  fixed opex 10,000 + debt service 36,000 = 46,000 needed EGI (no mgmt fee)
  occupancy BE = 46,000 / 100,000 GPR = 46%
  rent BE     = 46,000 / (100,000 − 10,000 vacancy) = 51.11% of scheduled
"""

import json
from pathlib import Path

import pytest

from app.services.proforma import engine

FIXTURES = Path(__file__).parent / "fixtures"


def analytic(**overrides) -> dict:
    deal = json.loads((FIXTURES / "analytic_acquisition.json").read_text())
    deal.update(overrides)
    return deal


def test_hand_computed_year1_and_flat_years():
    result = engine.compute(analytic())
    years = result["statement"]["breakEvens"]["years"]
    assert len(years) == 5
    assert years[0]["occupancy"] == pytest.approx(0.46)
    assert years[0]["rentFactor"] == pytest.approx(46_000 / 90_000)
    # Flat deal: every year identical.
    assert years[4]["occupancy"] == pytest.approx(years[0]["occupancy"])
    # Sidebar year-1 outputs mirror the first year row.
    assert result["outputs"]["breakEvenOccupancyYear1"] == pytest.approx(0.46)
    assert result["outputs"]["breakEvenRentYear1"] == pytest.approx(46_000 / 90_000)


def test_consistent_with_quick_screen_break_even():
    """The stabilized breakEvenOccupancy output (quick-screen formula) and
    the year-1 vector-based break-even agree on a flat stabilized deal."""
    outputs = engine.compute(analytic())["outputs"]
    assert outputs["breakEvenOccupancyYear1"] == pytest.approx(
        outputs["breakEvenOccupancy"]
    )


def test_impossible_year_returns_null_with_note():
    """25% interest -> debt service 150,000/yr; even 100% occupancy falls
    short. Null + note, never an out-of-range number."""
    result = engine.compute(analytic(interestRate=0.25))
    year1 = result["statement"]["breakEvens"]["years"][0]
    assert year1["occupancy"] is None
    assert year1["rentFactor"] is None
    assert any("100%" in n or "Cannot break even" in n for n in year1["notes"])
    assert "breakEvenOccupancyYear1" not in result["outputs"]


def test_construction_year_is_null_with_note():
    result = engine.compute({
        "dealType": "development", "propertyType": "multifamily",
        "dealName": "Dev", "landCost": 1_000_000, "hardCosts": 5_000_000,
        "softCosts": 500_000, "constructionMonths": 18,
        "grossPotentialRent": 800_000, "vacancyPct": 0.05,
        "realEstateTaxes": 50_000, "holdPeriodYears": 5,
        "exitCapRatePct": 0.07, "ltvOrLtc": 0.6, "interestRate": 0.07,
    })
    year1 = result["statement"]["breakEvens"]["years"][0]
    assert year1["occupancy"] is None
    assert "No operating revenue" in year1["notes"][0]
    # Once operating, break-evens exist again.
    later = result["statement"]["breakEvens"]["years"][3]
    assert later["occupancy"] is not None


def test_all_equity_no_opex_breaks_even_empty():
    result = engine.compute(
        analytic(ltvOrLtc=0, loanAmount=0, realEstateTaxes=0)
    )
    year1 = result["statement"]["breakEvens"]["years"][0]
    assert year1["occupancy"] == pytest.approx(0.0)
    assert year1["rentFactor"] == pytest.approx(0.0)
