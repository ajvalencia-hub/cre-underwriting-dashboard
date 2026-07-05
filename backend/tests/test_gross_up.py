"""I3: base-year gross-up.

Hand fixture: tenant A (6,000 SF, base_year_stop, 2026-2030) + tenant B
(4,000 SF, gross, expires 2026-12-31, p=0, 12-mo downtime) -> occupancy
2026 = 100%, 2027 = 60%, 2028+ = 100%. Pool $1,000/mo of which $400
variable, flat growth. Gross-up to 95%:

  2026 (base): ratio max(1, .95/1.0) = 1     -> 12,000/yr
  2027:        ratio .95/.60 = 1.58333       -> (600 + 400x1.58333)x12 = 14,800/yr
  A's 2027 recovery = 0.6 x (14,800 - 12,000)/12 = $140/mo
"""

import pytest

from app.services.proforma import engine, leases

POOL = [1_000.0] * 36
VARIABLE = [400.0] * 36


def two_tenant_inputs(**overrides) -> dict:
    inputs = {
        "commercialLeases": [
            {
                "tenant": "A", "suiteId": "A", "sf": 6_000,
                "startDate": "2026-01-01", "endDate": "2030-12-31",
                "baseRentPsfAnnual": 30, "escalationType": "none",
                "recoveryType": "base_year_stop", "freeRentMonths": 0,
            },
            {
                "tenant": "B", "suiteId": "B", "sf": 4_000,
                "startDate": "2026-01-01", "endDate": "2026-12-31",
                "baseRentPsfAnnual": 25, "escalationType": "none",
                "recoveryType": "gross", "freeRentMonths": 0,
            },
        ],
        "renewalProbability": 0, "downtimeMonths": 12,
        "marketRentPsf": 25, "marketRentGrowthPct": 0, "newTermYears": 5,
    }
    inputs.update(overrides)
    return inputs


def test_hand_computed_gross_up():
    income = leases.build_lease_income(
        two_tenant_inputs(), 36, POOL, 0.0,
        variable_recoverable_monthly=VARIABLE, gross_up_to=0.95,
    )
    assert income["occupancy"][0] == pytest.approx(1.0)
    assert income["occupancy"][12] == pytest.approx(0.6)
    # 2026 = base year: no delta.
    assert income["recoveries"][0] == pytest.approx(0)
    # 2027: A recovers its share of the grossed-up delta.
    assert income["recoveries"][12] == pytest.approx(140)
    # 2028: back to full occupancy -> delta vanishes again.
    assert income["recoveries"][24] == pytest.approx(0)


def test_without_gross_up_flat_pool_recovers_nothing():
    income = leases.build_lease_income(two_tenant_inputs(), 36, POOL, 0.0)
    assert all(r == pytest.approx(0) for r in income["recoveries"])


def test_fully_occupied_is_a_no_op():
    inputs = two_tenant_inputs()
    inputs["commercialLeases"][1]["endDate"] = "2030-12-31"  # B never expires
    grossed = leases.build_lease_income(
        inputs, 36, POOL, 0.0, variable_recoverable_monthly=VARIABLE, gross_up_to=0.95
    )
    raw = leases.build_lease_income(inputs, 36, POOL, 0.0)
    assert grossed["recoveries"] == pytest.approx(raw["recoveries"])


def test_never_grosses_down_below_actuals():
    """Target 50% with 60% actual occupancy: the ratio floors at 1 — the
    pool is never SHRUNK to a lower hypothetical occupancy."""
    income = leases.build_lease_income(
        two_tenant_inputs(), 36, POOL, 0.0,
        variable_recoverable_monthly=VARIABLE, gross_up_to=0.50,
    )
    assert all(r == pytest.approx(0, abs=1e-9) for r in income["recoveries"])


def test_occupancy_projection_matches_the_main_loop():
    """Drift guard: the gross-up's occupancy pre-pass must track the main
    loop's occupancy accumulation exactly."""
    inputs = two_tenant_inputs(renewalProbability=0.4, downtimeMonths=7)
    income = leases.build_lease_income(inputs, 48, [0.0] * 48, 0.0)
    projected = leases._occupancy_projection(
        inputs["commercialLeases"],
        leases._rollover_assumptions(inputs),
        48,
        10_000,
    )
    assert projected == pytest.approx(income["occupancy"])


def test_simple_expense_mode_warns_and_ignores():
    deal = {
        "dealType": "acquisition", "propertyType": "office",
        "purchasePrice": 2_000_000, "closingCostsPct": 0, "acquisitionFeePct": 0,
        "holdPeriodYears": 3, "exitCapRatePct": 0.07, "costOfSalePct": 0,
        "realEstateTaxes": 12_000,  # simple mode: no opexLineItems
        "managementFeePct": 0, "vacancyPct": 0, "creditLossPct": 0,
        "otherIncome": 0, "rentGrowthMode": "flat", "expenseGrowthMode": "flat",
        "ltvOrLtc": 0, "lpSplitPct": 0.9, "gpSplitPct": 0.1,
        "preferredReturnPct": 0.08, "waterfallTiers": [],
        **two_tenant_inputs(),
    }
    with_flag = engine.compute({**deal, "grossUpToPct": 0.95})
    without = engine.compute(deal)
    assert any("gross-up requires expense line detail" in w.lower() or
               "gross-up requires" in w for w in with_flag["warnings"])
    assert with_flag["outputs"] == without["outputs"]


def test_defaults_reproduce_run3():
    plain = leases.build_lease_income(two_tenant_inputs(), 36, POOL, 0.0)
    explicit = leases.build_lease_income(
        two_tenant_inputs(), 36, POOL, 0.0,
        variable_recoverable_monthly=None, gross_up_to=None,
    )
    assert plain["recoveries"] == pytest.approx(explicit["recoveries"])
