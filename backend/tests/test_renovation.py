"""J1: renovation program.

Hand fixture: 20x 1BR at $1,000 in-place, program renovates all 20 at
pace 2/mo from operating month 1, 1 month downtime per unit, $150 premium,
$10,000/unit. Flat growth, vacancy 0, credit 0, no other income, taxes
$60,000/yr, mgmt 0.

Hand month math (units enter in pairs; a unit entering month s is offline
in s, delivered from s+1):
  m1: offline 2, delivered 0  -> GPR 20,000, vacancy 2,000 (offline)
  m2: offline 2, delivered 2  -> GPR 20,000 + 2x150 = 20,300; vacancy 2,000
  m11: offline 0 (last pair entered m10), delivered 20
       -> GPR 20,000 + 20x150 = 23,000; vacancy 0
Capex: 2 x 10,000 = 20,000/mo in months 1..10 (below NOI).
"""

import json
from pathlib import Path

import pytest

from app.services.proforma import engine

FIXTURES = Path(__file__).parent / "regression" / "fixtures"


def reno_deal(**overrides) -> dict:
    deal = {
        "dealType": "acquisition", "propertyType": "multifamily",
        "purchasePrice": 2_400_000, "closingCostsPct": 0, "acquisitionFeePct": 0,
        "holdPeriodYears": 5, "exitCapRatePct": 0.06, "costOfSalePct": 0,
        "unitMix": [{"unitType": "1BR", "unitCount": 20, "inPlaceRent": 1_000}],
        "vacancyPct": 0, "creditLossPct": 0, "otherIncome": 0,
        "realEstateTaxes": 60_000, "managementFeePct": 0,
        "rentGrowthMode": "flat", "expenseGrowthMode": "flat",
        "renovationProgram": [{
            "unitType": "1BR", "unitsToReno": 20, "costPerUnit": 10_000,
            "premiumPerMonth": 150, "downtimeMonthsPerUnit": 1,
            "unitsPerMonth": 2, "startMonth": 1,
        }],
        "ltvOrLtc": 0, "lpSplitPct": 0.9, "gpSplitPct": 0.1,
        "preferredReturnPct": 0.08, "waterfallTiers": [],
    }
    deal.update(overrides)
    return deal


def test_hand_computed_rent_and_capex_vectors():
    result = engine.compute(reno_deal(renoFundingSource="operating_cash"))
    stmt = result["statement"]

    # Month 1: two units offline, none delivered.
    assert stmt["gpr"][1] == pytest.approx(20_000)
    assert stmt["vacancyLoss"][1] == pytest.approx(2_000)
    # Month 2: two delivered (premium), two offline.
    assert stmt["gpr"][2] == pytest.approx(20_300)
    assert stmt["vacancyLoss"][2] == pytest.approx(2_000)
    # Month 11: all 20 delivered, none offline.
    assert stmt["gpr"][11] == pytest.approx(23_000)
    assert stmt["vacancyLoss"][11] == pytest.approx(0)
    # Capex: 20,000/mo in months 1..10, then nothing (below NOI).
    for m in range(1, 11):
        assert stmt["renovationCapex"][m] == pytest.approx(20_000), m
    assert stmt["renovationCapex"][11] == pytest.approx(0)
    assert stmt["noi"][1] == pytest.approx(20_000 - 2_000 - 5_000)  # NOI ignores capex
    # Levered = NOI - capex during the program (all-equity deal).
    assert stmt["levered"][1] == pytest.approx(13_000 - 20_000)

    # Progress vectors.
    reno = stmt["renovation"]
    assert reno["unitsComplete"][2] == 2
    assert reno["unitsInProgress"][1] == 2
    assert reno["unitsRemaining"][1] == 18
    assert reno["unitsComplete"][11] == 20
    assert result["outputs"]["postRenoAvgRent"] == pytest.approx(1_150)


def test_budget_joins_basis_and_yoc_denominator():
    base = engine.compute(reno_deal())
    # yieldOnCost = stabilized in-place NOI / (price + 200k budget).
    stab_noi = 20 * 1_000 * 12 - 60_000  # 180,000 (vacancy 0)
    assert base["outputs"]["yieldOnCost"] == pytest.approx(stab_noi / 2_600_000)


def test_equity_at_close_vs_operating_cash_timing():
    at_close = engine.compute(reno_deal(renoFundingSource="equity_at_close"))
    as_incurred = engine.compute(reno_deal(renoFundingSource="operating_cash"))

    # Same total dollars out, different timing.
    assert sum(at_close["statement"]["levered"]) == pytest.approx(
        sum(as_incurred["statement"]["levered"])
    )
    assert at_close["statement"]["renovationCapex"][0] == pytest.approx(200_000)
    assert at_close["statement"]["renovationCapex"][1] == pytest.approx(0)
    assert as_incurred["statement"]["renovationCapex"][0] == pytest.approx(0)
    # Paying earlier is never a better IRR.
    assert at_close["outputs"]["leveredIrr"] <= as_incurred["outputs"]["leveredIrr"]
    # Uses at close carries the budget under equity_at_close.
    uses = dict(at_close["sourcesAndUses"]["uses"])
    assert uses["Renovation budget (equity escrow)"] == pytest.approx(200_000)


def test_operating_cash_shortfall_warns():
    """All-equity deal with a huge per-unit cost: month-1 operating cash
    can't cover the draws -> warning, never re-sequenced."""
    result = engine.compute(reno_deal(
        renoFundingSource="operating_cash",
        renovationProgram=[{
            "unitType": "1BR", "unitsToReno": 20, "costPerUnit": 100_000,
            "premiumPerMonth": 150, "downtimeMonthsPerUnit": 1,
            "unitsPerMonth": 4, "startMonth": 1,
        }],
    ))
    assert any("Renovation draws exceed cumulative operating cash" in w
               for w in result["warnings"])


def test_pace_faster_than_remaining_and_late_start():
    fast = engine.compute(reno_deal(renovationProgram=[{
        "unitType": "1BR", "unitsToReno": 5, "costPerUnit": 10_000,
        "premiumPerMonth": 150, "downtimeMonthsPerUnit": 1,
        "unitsPerMonth": 4, "startMonth": 1,
    }]))
    reno = fast["statement"]["renovation"]
    assert reno["spendSchedule"][1] == pytest.approx(40_000)  # 4 units
    assert reno["spendSchedule"][2] == pytest.approx(10_000)  # last 1, not 4
    assert reno["unitsComplete"][3] == 5

    late = engine.compute(reno_deal(renovationProgram=[{
        "unitType": "1BR", "unitsToReno": 5, "costPerUnit": 10_000,
        "premiumPerMonth": 150, "downtimeMonthsPerUnit": 1,
        "unitsPerMonth": 2, "startMonth": 100,  # after the 60-month exit
    }]))
    assert any("after the exit" in w for w in late["warnings"])
    assert "renovation" not in late["statement"]  # program never runs


def test_defaults_reproduce_run4():
    value_add = json.loads((FIXTURES / "value_add_multifamily.json").read_text())
    plain = engine.compute(value_add)
    explicit = engine.compute({**value_add, "renovationProgram": [],
                               "renoFundingSource": "equity_at_close"})
    assert plain["outputs"] == explicit["outputs"]
    assert "renovationCapex" not in plain["statement"]
