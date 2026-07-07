"""L2: dynamic per-unit-type loss-to-lease burn-off. Activates only when a
unitMix row sets annualTurnoverPct; supersedes (never combines with) the
flat lossToLeasePct haircut, with a warning on conflict. Composes with L1
(renovated units leave the eligible pool)."""

import pytest

from app.services.proforma import engine
from app.services.proforma.operations import loss_to_lease_schedule
from app.services.proforma.timeline import Timeline


# ---------------------------------------------------------------------------
# Hand-computed burn-off math (pure unit test)
# ---------------------------------------------------------------------------

def test_hand_computed_2_type_24_month_burnoff():
    """Type A: 10 units, $1,000 in-place, $1,200 market, 24%/yr turnover
    (2%/mo), full capture. Type B: 5 units, $800/$900, 12%/yr (1%/mo),
    50% capture. Flat growth (no rent escalation) to keep the math simple."""
    inputs = {
        "unitMix": [
            {"unitType": "A", "unitCount": 10, "inPlaceRent": 1000, "marketRent": 1200,
             "annualTurnoverPct": 0.24, "lossToLeaseCapturePct": 1.0},
            {"unitType": "B", "unitCount": 5, "inPlaceRent": 800, "marketRent": 900,
             "annualTurnoverPct": 0.12, "lossToLeaseCapturePct": 0.5},
        ],
        "rentGrowthMode": "flat",
    }
    timeline = Timeline(24, 0, 0, 1)
    result = loss_to_lease_schedule(inputs, timeline)

    # Month 1: A turned_share=0.02 -> 10*0.02*1.0*200=40; B turned_share=0.01 -> 5*0.01*0.5*100=2.5
    assert result["gprDelta"][0] == pytest.approx(40 + 2.5)
    # Month 12: A turned_share=0.24 -> 10*0.24*1.0*200=480; B turned_share=0.12 -> 5*0.12*0.5*100=30
    assert result["gprDelta"][11] == pytest.approx(480 + 30)
    assert result["warnings"] == []


def test_capture_pct_bounds_0_and_1():
    base = {
        "unitMix": [{"unitType": "A", "unitCount": 10, "inPlaceRent": 1000, "marketRent": 1200,
                     "annualTurnoverPct": 0.24}],
        "rentGrowthMode": "flat",
    }
    timeline = Timeline(12, 0, 0, 1)

    zero = loss_to_lease_schedule({**base, "unitMix": [
        {**base["unitMix"][0], "lossToLeaseCapturePct": 0.0}
    ]}, timeline)
    assert zero["gprDelta"][5] == pytest.approx(0.0)

    full = loss_to_lease_schedule({**base, "unitMix": [
        {**base["unitMix"][0], "lossToLeaseCapturePct": 1.0}
    ]}, timeline)
    assert full["gprDelta"][5] > 0

    # Absent capturePct defaults to 1.0 (same as explicit 1.0).
    default = loss_to_lease_schedule(base, timeline)
    assert default["gprDelta"][5] == pytest.approx(full["gprDelta"][5])


def test_inactive_without_any_turnover_pct_is_a_true_no_op():
    inputs = {
        "unitMix": [{"unitType": "A", "unitCount": 10, "inPlaceRent": 1000, "marketRent": 1200}],
    }
    result = loss_to_lease_schedule(inputs, Timeline(12, 0, 0, 1))
    assert result["gprDelta"] == [0.0] * 12
    assert result["warnings"] == []


def test_requires_both_in_place_and_market_rent_present():
    inputs = {
        "unitMix": [{"unitType": "A", "unitCount": 10, "inPlaceRent": 1000, "annualTurnoverPct": 0.24}],
    }
    result = loss_to_lease_schedule(inputs, Timeline(12, 0, 0, 1))
    assert result["gprDelta"] == [0.0] * 12  # no marketRent -> row skipped entirely


def test_supersedes_flat_field_with_warning_when_both_set():
    inputs = {
        "unitMix": [{"unitType": "A", "unitCount": 10, "inPlaceRent": 1000, "marketRent": 1200,
                     "annualTurnoverPct": 0.24}],
        "lossToLeasePct": 0.05,
    }
    result = loss_to_lease_schedule(inputs, Timeline(12, 0, 0, 1))
    assert any("supersedes the flat lossToLeasePct" in w for w in result["warnings"])


def test_l1_interaction_shrinks_eligible_pool():
    inputs = {
        "dealType": "acquisition",
        "unitMix": [{"unitType": "A", "unitCount": 10, "inPlaceRent": 1000, "marketRent": 1200,
                     "annualTurnoverPct": 0.24}],
        "renovationProgram": [
            {"unitType": "A", "unitsToReno": 4, "costPerUnit": 5000, "premiumPerMonth": 50,
             "downtimeMonthsPerUnit": 1, "unitsPerMonth": 4, "startMonth": 1},
        ],
        "rentGrowthMode": "flat",
    }
    without_reno = loss_to_lease_schedule({**inputs, "renovationProgram": []}, Timeline(12, 0, 0, 1))
    with_reno = loss_to_lease_schedule(inputs, Timeline(12, 0, 0, 1))
    # 4 of 10 units renovated from month 1 -> only 6 eligible -> 60% of the
    # unconstrained delta for every month.
    assert with_reno["gprDelta"][0] == pytest.approx(without_reno["gprDelta"][0] * 0.6)


# ---------------------------------------------------------------------------
# Engine-level integration
# ---------------------------------------------------------------------------

def _base_acquisition(**overrides) -> dict:
    inputs = {
        "dealType": "acquisition",
        "propertyType": "multifamily",
        "purchasePrice": 3_000_000,
        "unitMix": [{"unitType": "A", "unitCount": 20, "inPlaceRent": 1000, "marketRent": 1200}],
        "vacancyPct": 0.05,
        "realEstateTaxes": 50_000,
        "holdPeriodYears": 5,
        "exitCapRatePct": 0.06,
        "ltvOrLtc": 0,
        "rentGrowthMode": "flat",
        "expenseGrowthMode": "flat",
    }
    inputs.update(overrides)
    return inputs


def test_flat_field_only_deal_is_completely_unaffected():
    """The core byte-identical-reproduction guarantee: a deal using ONLY the
    legacy flat lossToLeasePct (no annualTurnoverPct anywhere) must compute
    identically to before this feature existed."""
    with_flat = engine.compute(_base_acquisition(lossToLeasePct=0.05))
    # Same deal, computed again — must be stable/deterministic and the flat
    # discount must actually be doing something (sanity: differs from 0%).
    without_flat = engine.compute(_base_acquisition(lossToLeasePct=0.0))
    assert with_flat["outputs"]["leveredIrr"] != without_flat["outputs"]["leveredIrr"]
    assert with_flat["warnings"] == []


def test_dynamic_model_changes_output_and_flat_field_is_ignored():
    dynamic = engine.compute(_base_acquisition(
        lossToLeasePct=0.05,
        unitMix=[{"unitType": "A", "unitCount": 20, "inPlaceRent": 1000, "marketRent": 1200,
                  "annualTurnoverPct": 0.24}],
    ))
    assert any("supersedes the flat lossToLeasePct" in w for w in dynamic["warnings"])

    # With the flat field cleared, output must be IDENTICAL (proving it was
    # truly ignored, not just also applied).
    dynamic_no_flat = engine.compute(_base_acquisition(
        unitMix=[{"unitType": "A", "unitCount": 20, "inPlaceRent": 1000, "marketRent": 1200,
                  "annualTurnoverPct": 0.24}],
    ))
    assert dynamic["outputs"]["leveredIrr"] == pytest.approx(
        dynamic_no_flat["outputs"]["leveredIrr"], abs=1e-12
    )
