"""J2: loss-to-lease burn-off.

Hand fixture: type A = 10 units, in-place $1,000, market $1,200 (gap $200),
turnover 24%/yr (f = 2%/mo); type B = 5 units at $900 with NO turnover set
(LTL inactive for B). Flat growth, vacancy 0, credit 0, capture 1.

Month-om algebra (A only): in-place share s = 0.98^(om−1);
scheduled uplift = 10·(1−s)·200; loss-to-lease = 10·s·200.
  om=1:  s=1        -> uplift 0,       LTL 2,000  (GPR == baseline)
  om=13: s=0.98^12  -> uplift 10·(1−0.98^12)·200, LTL 10·0.98^12·200
"""

import json
from pathlib import Path

import pytest

from app.services.proforma import engine

FIXTURES = Path(__file__).parent / "regression" / "fixtures"


def ltl_deal(**overrides) -> dict:
    deal = {
        "dealType": "acquisition", "propertyType": "multifamily",
        "purchasePrice": 2_000_000, "closingCostsPct": 0, "acquisitionFeePct": 0,
        "holdPeriodYears": 3, "exitCapRatePct": 0.06, "costOfSalePct": 0,
        "unitMix": [
            {"unitType": "A", "unitCount": 10, "inPlaceRent": 1_000,
             "marketRent": 1_200, "annualTurnoverPct": 0.24},
            {"unitType": "B", "unitCount": 5, "inPlaceRent": 900},
        ],
        "vacancyPct": 0, "creditLossPct": 0, "otherIncome": 0,
        "realEstateTaxes": 30_000, "managementFeePct": 0,
        "rentGrowthMode": "flat", "expenseGrowthMode": "flat",
        "ltvOrLtc": 0, "lpSplitPct": 0.9, "gpSplitPct": 0.1,
        "preferredReturnPct": 0.08, "waterfallTiers": [],
    }
    deal.update(overrides)
    return deal


def test_hand_computed_burn_off_over_24_months():
    result = engine.compute(ltl_deal())
    stmt = result["statement"]

    # Month 1: fully in-place — scheduled GPR equals the no-LTL baseline.
    assert stmt["gpr"][1] == pytest.approx(10 * 1_000 + 5 * 900)
    assert stmt["lossToLease"]["lossToLease"][1] == pytest.approx(10 * 200)
    # marketGpr covers LTL-active types only (B has no market rent set).
    assert stmt["lossToLease"]["marketGpr"][1] == pytest.approx(10 * 1_200)

    for om in (2, 13, 24):
        s = 0.98 ** (om - 1)
        expected_uplift = 10 * (1 - s) * 200
        assert stmt["gpr"][om] == pytest.approx(14_500 + expected_uplift), om
        assert stmt["lossToLease"]["lossToLease"][om] == pytest.approx(10 * s * 200), om
        # Build identity: market GPR − LTL = the active types' scheduled rent.
        scheduled_a = stmt["gpr"][om] - 5 * 900
        assert stmt["lossToLease"]["marketGpr"][om] - stmt["lossToLease"]["lossToLease"][om] == pytest.approx(scheduled_a), om

    # Sidebar output: year-1 LTL dollars.
    expected_year1 = sum(10 * (0.98 ** (om - 1)) * 200 for om in range(1, 13))
    assert result["outputs"]["year1LossToLease"] == pytest.approx(expected_year1)


def test_capture_bounds():
    zero = engine.compute(ltl_deal(lossToLeaseCapturePct=0))
    # Capture 0: turned units re-let at in-place — scheduled never moves...
    assert zero["statement"]["gpr"][24] == pytest.approx(14_500)
    # ...and the LTL line stays at the full gap.
    assert zero["statement"]["lossToLease"]["lossToLease"][24] == pytest.approx(2_000)

    full = engine.compute(ltl_deal(lossToLeaseCapturePct=1.0))
    default = engine.compute(ltl_deal())
    assert full["statement"]["gpr"] == pytest.approx(default["statement"]["gpr"])


def test_renovation_supersedes_ltl():
    """4 units of A renovate (pace 4, start month 1, 1-mo downtime, $150
    premium): they exit the LTL pool at start; delivered units re-base to
    FULL market + premium."""
    result = engine.compute(ltl_deal(
        renovationProgram=[{
            "unitType": "A", "unitsToReno": 4, "costPerUnit": 5_000,
            "premiumPerMonth": 150, "downtimeMonthsPerUnit": 1,
            "unitsPerMonth": 4, "startMonth": 1,
        }],
        renoFundingSource="operating_cash",
    ))
    stmt = result["statement"]
    # Month 2: pool = 6, s = 0.98; delivered 4 at market + premium.
    s = 0.98
    expected_gpr = (
        14_500                      # in-place base (all units incl. reno'd)
        + 6 * (1 - s) * 200         # LTL uplift on the shrunken pool
        + 4 * 200                   # delivered units re-based to market
        + 4 * 150                   # J1 premium
    )
    assert stmt["gpr"][2] == pytest.approx(expected_gpr)
    # Month 1: 4 offline (vacancy), no uplift yet.
    assert stmt["vacancyLoss"][1] == pytest.approx(4 * 1_000)
    # Market GPR now carries the delivered premium as potential.
    assert stmt["lossToLease"]["marketGpr"][2] == pytest.approx(10 * 1_200 + 4 * 150)


def test_ltl_needs_both_rents_and_turnover():
    # Turnover set but no market rent -> inactive.
    no_market = engine.compute(ltl_deal(unitMix=[
        {"unitType": "A", "unitCount": 10, "inPlaceRent": 1_000, "annualTurnoverPct": 0.24},
    ]))
    assert "lossToLease" not in no_market["statement"]
    assert "year1LossToLease" not in no_market["outputs"]


def test_defaults_reproduce_run4():
    value_add = json.loads((FIXTURES / "value_add_multifamily.json").read_text())
    plain = engine.compute(value_add)
    assert "lossToLease" not in plain["statement"]
    with_capture_only = engine.compute({**value_add, "lossToLeaseCapturePct": 1.0})
    assert plain["outputs"] == with_capture_only["outputs"]
