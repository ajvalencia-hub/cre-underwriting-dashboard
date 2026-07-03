"""F2: timeline, development budget/spend, construction financing, and the
operations GPR-source/growth logic — each against small hand-calculated cases.
"""

import pytest

from app.services.proforma.debt import amortization_schedule, construction_financing
from app.services.proforma.development import (
    build_budget,
    monthly_cost_schedule,
    s_curve_weights,
)
from app.services.proforma.operations import (
    annual_gpr_and_other_income,
    build_noi_vector,
    stabilized_annual_noi,
)
from app.services.proforma.timeline import Timeline, build_timeline


# ---------------------------------------------------------------- timeline

def test_acquisition_timeline_is_stabilized_from_month_one():
    tl, warnings = build_timeline("acquisition", 5)
    assert (tl.total_months, tl.stabilization_month) == (60, 1)
    assert tl.phase(1) == "stabilized"
    assert warnings == []


def test_development_phases():
    tl, _ = build_timeline("development", 5, construction_months=12, lease_up_months=6)
    assert tl.stabilization_month == 19
    assert tl.phase(12) == "construction"
    assert tl.phase(13) == "lease_up"
    assert tl.phase(19) == "stabilized"


def test_lease_up_longer_than_hold_warns_but_does_not_crash():
    tl, warnings = build_timeline("development", 3, construction_months=6, lease_up_months=60)
    assert tl.total_months == 36
    assert any("sold before stabilizing" in w for w in warnings)


# -------------------------------------------------------------- development

def test_budget_hand_calc():
    # land 1.0M, hard 8.0M, soft 1.0M, contingency 5% x 9.0M = 450k,
    # fee 4% x 9.45M = 378k, total ex financing 10.828M.
    budget = build_budget(1_000_000, 8_000_000, 1_000_000, 0.05, 0.04)
    assert budget.contingency == pytest.approx(450_000)
    assert budget.developer_fee == pytest.approx(378_000)
    assert budget.total_ex_financing == pytest.approx(10_828_000)


def test_s_curve_weights_sum_to_one_and_peak_mid_build():
    weights = s_curve_weights(12)
    assert sum(weights) == pytest.approx(1.0, abs=1e-12)
    assert max(weights) == pytest.approx(weights[5], abs=1e-12) or max(weights) == pytest.approx(
        weights[6], abs=1e-12
    )
    assert weights[0] < weights[5]  # slow start, fast middle


def test_cost_schedule_land_at_close_and_totals_preserved():
    budget = build_budget(1_000_000, 8_000_000, 1_000_000, 0.05, 0.04)
    schedule = monthly_cost_schedule(budget, 12)
    assert len(schedule) == 13  # month 0 + 12 construction months
    assert schedule[0] == pytest.approx(1_000_000)  # land at close
    assert sum(schedule) == pytest.approx(budget.total_ex_financing)


# ------------------------------------------------------------------- debt

def test_construction_financing_equity_first_hand_calc():
    # Costs 100 at months 0/1/2; equity 150; 12% annual = 1%/mo.
    # m0: all equity (100), no draw, no interest at close.
    # m1: equity 50 + draw 50 -> balance 50, interest 0.50 -> 50.50.
    # m2: draw 100 -> 150.50, interest 1.505 -> 152.005.
    result = construction_financing([100.0, 100.0, 100.0], 150.0, 0.12)
    assert result.equity_funded == pytest.approx([100.0, 50.0, 0.0])
    assert result.draws == pytest.approx([0.0, 50.0, 100.0])
    assert result.interest_capitalized == pytest.approx(2.005)
    assert result.ending_balance == pytest.approx(152.005)


def test_amortization_io_then_level_payments():
    schedule = amortization_schedule(1000.0, 0.12, 10, io_months=2, months=4)
    assert schedule[0].interest == pytest.approx(10.0)
    assert schedule[0].principal == 0.0
    assert schedule[1].balance == pytest.approx(1000.0)
    # After IO the payment is the 10-year level payment; principal reduces.
    assert schedule[2].principal > 0
    assert schedule[3].balance < schedule[2].balance


# -------------------------------------------------------------- operations

def test_gpr_source_precedence_unit_mix_wins():
    inputs = {
        "unitMix": [
            {"unitType": "1BR", "unitCount": 10, "inPlaceRent": 1000},
            {"unitType": "2BR", "unitCount": 5, "inPlaceRent": 2000},
        ],
        "lossToLeasePct": 0.05,
        "concessionsPct": 0.05,
        "parkingIncome": 1200,
        "rubsIncome": 800,
        "grossPotentialRent": 999999,  # must be ignored
    }
    gpr, other, source, _ = annual_gpr_and_other_income(inputs)
    assert source == "unitMix"
    assert gpr == pytest.approx(240_000 * 0.9)  # (10x1000 + 5x2000) x 12 x (1-10%)
    assert other == pytest.approx(2000)


def test_gpr_source_per_sf_shape():
    inputs = {"rentableSf": 10_000, "rentPsf": 20, "nnnRecoveriesPsf": 5}
    gpr, other, source, _ = annual_gpr_and_other_income(inputs)
    assert source == "perSf"
    assert gpr == pytest.approx(200_000)
    assert other == pytest.approx(50_000)


def test_growth_steps_annually_and_lease_up_ramps():
    inputs = {
        "grossPotentialRent": 120_000,
        "vacancyPct": 0.0,
        "creditLossPct": 0.0,
        "rentGrowthMode": "per_year",
        "rentGrowthPct": 0.10,
        "expenseGrowthMode": "flat",
    }
    tl = Timeline(24, 0, 0, 1)
    ops = build_noi_vector(inputs, tl)
    assert ops["gpr"][0] == pytest.approx(10_000)  # month 1
    assert ops["gpr"][11] == pytest.approx(10_000)  # month 12, still year 1
    assert ops["gpr"][12] == pytest.approx(11_000)  # month 13, +10%

    # Development ramp: 6 construction months, 4 lease-up, stabilized at 11.
    dev_tl = Timeline(24, 6, 4, 11)
    dev = build_noi_vector({**inputs, "vacancyPct": 0.05}, dev_tl)
    assert dev["occupancy"][5] == 0.0  # construction
    assert dev["occupancy"][6] == pytest.approx(0.95 * 0.25)  # 1st lease-up month
    assert dev["occupancy"][10] == pytest.approx(0.95)  # stabilized
    # Growth clock starts at operations, not at close:
    assert dev["gpr"][6] == pytest.approx(10_000)


def test_stabilized_annual_noi_matches_vector_math():
    inputs = {
        "grossPotentialRent": 100_000,
        "vacancyPct": 0.1,
        "creditLossPct": 0.0,
        "realEstateTaxes": 10_000,
        "managementFeePct": 0.0,
        "rentGrowthMode": "flat",
        "expenseGrowthMode": "flat",
    }
    assert stabilized_annual_noi(inputs) == pytest.approx(80_000)
    ops = build_noi_vector(inputs, Timeline(12, 0, 0, 1))
    assert sum(ops["noi"]) == pytest.approx(80_000)
