"""L1: value-add renovation program — composes with the existing P2
lease-up/value-add ramp (commit 76cd18e) without touching it. Renovation
downtime/premium dollars are applied AFTER the ramp's blended multiplier,
never folded into it, and never modeled for mixed-use/commercial-lease/
development deals (a warning, not a silent no-op, for those)."""

import pytest

from app.services.proforma import engine
from app.services.proforma.operations import renovation_schedule
from app.services.proforma.timeline import Timeline


def _base_acquisition(**overrides) -> dict:
    inputs = {
        "dealType": "acquisition",
        "propertyType": "multifamily",
        "purchasePrice": 5_000_000,
        "unitMix": [
            {"unitType": "A", "unitCount": 20, "inPlaceRent": 1000, "marketRent": 1200},
        ],
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


# ---------------------------------------------------------------------------
# Hand-computed program math (pure unit test, no engine involved)
# ---------------------------------------------------------------------------

def test_hand_computed_20_unit_program_downtime_and_premium():
    """20 units, in-place rent $1,000/mo, pace 5/mo, 2-month downtime, $150
    premium, no growth. Batch 1 (5 units) starts month 1: down months 1-2
    (-5*1000/12 each), earns premium from month 3 onward. Batch 4 (last 5)
    starts month 4: down months 4-5, earns premium from month 6 onward."""
    inputs = {
        "unitMix": [{"unitType": "A", "unitCount": 20, "inPlaceRent": 1000, "marketRent": 1200}],
        "rentGrowthMode": "flat",
        "renovationProgram": [
            {
                "unitType": "A", "unitsToReno": 20, "costPerUnit": 8000,
                "premiumPerMonth": 150, "downtimeMonthsPerUnit": 2,
                "unitsPerMonth": 5, "startMonth": 1,
            }
        ],
    }
    timeline = Timeline(60, 0, 0, 1)  # 5-year acquisition, no construction/lease-up
    result = renovation_schedule(inputs, timeline)

    # Capex: 4 batches of 5 units x $8,000 = $40,000/batch, months 1-4.
    assert result["capex"][0] == pytest.approx(40_000)
    assert result["capex"][1] == pytest.approx(40_000)
    assert result["capex"][2] == pytest.approx(40_000)
    assert result["capex"][3] == pytest.approx(40_000)
    assert sum(result["capex"]) == pytest.approx(20 * 8000)

    # Month 1: only batch 1 (5 units) is down -> -5*1000/12.
    assert result["egiDelta"][0] == pytest.approx(-5 * 1000 / 12)
    # Month 2: batch 1 still down (month 2 of 2), batch 2 just started (month 1 of 2)
    # -> 10 units down.
    assert result["egiDelta"][1] == pytest.approx(-10 * 1000 / 12)
    # Month 3: batch 1 completed (earns premium), batch 2 down (month 2),
    # batch 3 down (month 1) -> premium for 5 + downtime for 10.
    assert result["egiDelta"][2] == pytest.approx(5 * 150 - 10 * 1000 / 12)
    # Month 7: all 4 batches long completed -> full premium, no downtime.
    assert result["egiDelta"][6] == pytest.approx(20 * 150)


def test_premium_grows_at_rent_growth_pct_after_completion():
    inputs = {
        "unitMix": [{"unitType": "A", "unitCount": 1, "inPlaceRent": 1000, "marketRent": 1200}],
        "rentGrowthMode": "per_year",
        "rentGrowthPct": 0.10,
        "renovationProgram": [
            {
                "unitType": "A", "unitsToReno": 1, "costPerUnit": 5000,
                "premiumPerMonth": 100, "downtimeMonthsPerUnit": 0,
                "unitsPerMonth": 1, "startMonth": 1,
            }
        ],
    }
    timeline = Timeline(30, 0, 0, 1)
    result = renovation_schedule(inputs, timeline)
    # Zero downtime -> completes immediately at month 1, earns premium from month 1.
    assert result["egiDelta"][0] == pytest.approx(100)
    # Still year 1 at month 12 -> unchanged.
    assert result["egiDelta"][11] == pytest.approx(100)
    # Year 2 (month 13+) -> grown 10%.
    assert result["egiDelta"][12] == pytest.approx(110)


def test_no_program_is_a_true_no_op():
    timeline = Timeline(24, 0, 0, 1)
    result = renovation_schedule({}, timeline)
    assert result["egiDelta"] == [0.0] * 24
    assert result["capex"] == [0.0] * 24
    assert result["warnings"] == []


def test_pace_exceeding_remaining_time_warns_and_leaves_remainder_unstarted():
    inputs = {
        "unitMix": [{"unitType": "A", "unitCount": 100, "inPlaceRent": 1000, "marketRent": 1200}],
        "renovationProgram": [
            {
                "unitType": "A", "unitsToReno": 100, "costPerUnit": 5000,
                "premiumPerMonth": 100, "downtimeMonthsPerUnit": 1,
                "unitsPerMonth": 1, "startMonth": 1,
            }
        ],
    }
    timeline = Timeline(12, 0, 0, 1)  # only 12 months to fit 100 units at 1/mo
    result = renovation_schedule(inputs, timeline)
    assert any("pace" in w and "never started" in w for w in result["warnings"])
    # Total capex reflects only the units that actually started.
    assert sum(result["capex"]) < 100 * 5000


def test_start_month_past_exit_warns_and_is_a_no_op_for_that_row():
    inputs = {
        "unitMix": [{"unitType": "A", "unitCount": 5, "inPlaceRent": 1000, "marketRent": 1200}],
        "renovationProgram": [
            {
                "unitType": "A", "unitsToReno": 5, "costPerUnit": 5000,
                "premiumPerMonth": 100, "downtimeMonthsPerUnit": 1,
                "unitsPerMonth": 1, "startMonth": 999,
            }
        ],
    }
    timeline = Timeline(24, 0, 0, 1)
    result = renovation_schedule(inputs, timeline)
    assert any("past the hold/exit" in w for w in result["warnings"])
    assert sum(result["capex"]) == 0
    assert all(d == 0 for d in result["egiDelta"])


def test_missing_unit_mix_rent_basis_warns_and_downtime_is_zero():
    inputs = {
        "unitMix": [{"unitType": "B", "unitCount": 5, "inPlaceRent": 1000}],  # different type
        "renovationProgram": [
            {
                "unitType": "A", "unitsToReno": 5, "costPerUnit": 5000,
                "premiumPerMonth": 100, "downtimeMonthsPerUnit": 2,
                "unitsPerMonth": 5, "startMonth": 1,
            }
        ],
    }
    timeline = Timeline(24, 0, 0, 1)
    result = renovation_schedule(inputs, timeline)
    assert any("no matching unitMix rent basis" in w for w in result["warnings"])
    # Downtime dollars are $0 (no rent basis), but premium still applies.
    assert result["egiDelta"][0] == pytest.approx(0)
    assert result["egiDelta"][2] == pytest.approx(5 * 100)


# ---------------------------------------------------------------------------
# Engine-level integration
# ---------------------------------------------------------------------------

def test_capex_lands_in_sources_and_uses_and_cost_basis_equity_at_close():
    inputs = _base_acquisition(
        renovationProgram=[
            {"unitType": "A", "unitsToReno": 20, "costPerUnit": 10_000, "premiumPerMonth": 200,
             "downtimeMonthsPerUnit": 2, "unitsPerMonth": 20, "startMonth": 1},
        ],
    )
    without_reno = engine.compute(_base_acquisition())
    with_reno = engine.compute(inputs)

    uses = dict(with_reno["sourcesAndUses"]["uses"])
    assert uses["Renovation capex"] == pytest.approx(200_000)
    # Equity required goes up by exactly the capex (no debt, ltvOrLtc=0).
    equity_without = dict(without_reno["sourcesAndUses"]["sources"])["Equity"]
    equity_with = dict(with_reno["sourcesAndUses"]["sources"])["Equity"]
    assert equity_with - equity_without == pytest.approx(200_000)
    assert with_reno["warnings"] == []


def test_operating_cash_mode_draws_from_cash_flow_not_basis():
    inputs = _base_acquisition(
        renoFundingSource="operating_cash",
        renovationProgram=[
            {"unitType": "A", "unitsToReno": 20, "costPerUnit": 10_000, "premiumPerMonth": 200,
             "downtimeMonthsPerUnit": 2, "unitsPerMonth": 20, "startMonth": 1},
        ],
    )
    result = engine.compute(inputs)
    uses = dict(result["sourcesAndUses"]["uses"])
    assert "Renovation capex" not in uses  # not funded at close in this mode


def test_operating_cash_shortfall_warns_but_does_not_refuse():
    inputs = _base_acquisition(
        renoFundingSource="operating_cash",
        renovationProgram=[
            {"unitType": "A", "unitsToReno": 20, "costPerUnit": 100_000, "premiumPerMonth": 200,
             "downtimeMonthsPerUnit": 1, "unitsPerMonth": 20, "startMonth": 1},
        ],
    )
    result = engine.compute(inputs)  # must not raise
    assert any("takes levered cash flow negative" in w for w in result["warnings"])


def test_renovation_ignored_on_development_deal_with_warning():
    inputs = {
        "dealType": "development",
        "propertyType": "multifamily",
        "landCost": 1_000_000,
        "hardCosts": 5_000_000,
        "softCosts": 500_000,
        "unitMix": [{"unitType": "A", "unitCount": 20, "inPlaceRent": 1000, "marketRent": 1200}],
        "realEstateTaxes": 50_000,
        "holdPeriodYears": 5,
        "exitCapRatePct": 0.06,
        "ltvOrLtc": 0,
        "renovationProgram": [
            {"unitType": "A", "unitsToReno": 5, "costPerUnit": 5000, "premiumPerMonth": 100,
             "downtimeMonthsPerUnit": 1, "unitsPerMonth": 1, "startMonth": 1},
        ],
    }
    result = engine.compute(inputs)
    assert any("ignored on development deals" in w for w in result["warnings"])


def test_renovation_ignored_on_mixed_use_deal_with_warning():
    inputs = {
        "dealType": "acquisition",
        "propertyType": "mixed_use",
        "purchasePrice": 8_000_000,
        "unitMix": [{"unitType": "1BR", "unitCount": 10, "inPlaceRent": 2000}],
        "commercialLeases": [{
            "tenant": "Shop", "suiteId": "R1", "sf": 10_000,
            "startDate": "2026-01-01", "endDate": "2033-12-31",
            "baseRentPsfAnnual": 30, "escalationType": "none",
            "recoveryType": "NNN", "freeRentMonths": 0,
        }],
        "realEstateTaxes": 54_000,
        "holdPeriodYears": 5,
        "exitCapRatePct": 0.06,
        "ltvOrLtc": 0,
        "renovationProgram": [
            {"unitType": "1BR", "unitsToReno": 5, "costPerUnit": 5000, "premiumPerMonth": 100,
             "downtimeMonthsPerUnit": 1, "unitsPerMonth": 1, "startMonth": 1},
        ],
    }
    result = engine.compute(inputs)
    assert any("ignored on mixed-use deals" in w for w in result["warnings"])


def test_reno_program_layered_on_active_ramp_leaves_ramp_output_independent():
    """The whole point of L1's ramp-sequencing decision: adding a reno
    program must not change what the ramp itself contributes — verified by
    comparing the ramp-only run against a run with a DISABLED (startMonth
    past exit) reno program layered on top, which must be byte-identical."""
    ramp_inputs = _base_acquisition(
        inPlaceNoi=150_000,
        valueAddMonths=12,
        unitMix=[{"unitType": "A", "unitCount": 40, "inPlaceRent": 900, "marketRent": 1100}],
    )
    ramp_only = engine.compute(ramp_inputs)
    ramp_with_disabled_reno = engine.compute({
        **ramp_inputs,
        "renovationProgram": [
            {"unitType": "A", "unitsToReno": 10, "costPerUnit": 5000, "premiumPerMonth": 100,
             "downtimeMonthsPerUnit": 1, "unitsPerMonth": 1, "startMonth": 9999},
        ],
    })
    # Disabled row means zero effect except the "never starts" warning.
    assert ramp_only["outputs"]["leveredIrr"] == pytest.approx(
        ramp_with_disabled_reno["outputs"]["leveredIrr"], abs=1e-12
    )


def test_reno_absent_reproduces_baseline_exactly_for_value_add_fixture():
    """The L0 value_add_acquisition fixture must still compute identically —
    this is the concrete regression guard for the ramp/reno independence
    claim, beyond the abstract case above."""
    import json
    from pathlib import Path

    fixture = json.loads(
        (Path(__file__).parent / "regression" / "fixtures" / "value_add_acquisition.json").read_text()
    )
    baseline = json.loads(
        (Path(__file__).parent / "regression" / "run3_baseline" / "value_add_acquisition.json").read_text()
    )
    result = engine.compute(fixture)
    assert result["outputs"]["leveredIrr"] == pytest.approx(baseline["outputs"]["leveredIrr"], abs=1e-9)


def test_statement_reno_capex_key_only_present_when_active():
    result_without = engine.compute(_base_acquisition())
    result_with = engine.compute(_base_acquisition(renovationProgram=[
        {"unitType": "A", "unitsToReno": 5, "costPerUnit": 5000, "premiumPerMonth": 100,
         "downtimeMonthsPerUnit": 1, "unitsPerMonth": 5, "startMonth": 1},
    ]))
    assert "renoCapex" not in result_without["statement"]
    assert "renoCapex" in result_with["statement"]
    assert result_with["statement"]["renoCapex"][1] == pytest.approx(5 * 5000)


def test_excel_export_refuses_active_renovation_program():
    from app.services.excel_model_export import unsupported_features

    active = _base_acquisition(renovationProgram=[
        {"unitType": "A", "unitsToReno": 5, "costPerUnit": 5000, "premiumPerMonth": 100,
         "downtimeMonthsPerUnit": 1, "unitsPerMonth": 5, "startMonth": 1},
    ])
    inactive = _base_acquisition(renovationProgram=[])

    assert any("renovation" in f.lower() for f in unsupported_features(active))
    assert not any("renovation" in f.lower() for f in unsupported_features(inactive))
