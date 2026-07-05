"""I14: lease-engine performance guard.

A generated 50-lease commercial roll on a 10-year monthly grid (mixed
recovery types, escalations, staggered expiries, rollover generations with
TI/LC and downtime) must compute inside a hard wall-clock budget, and the
engine must build the lease income a CONSTANT number of times per compute —
a regression that re-evaluates per lease or per month explodes the call
count long before the clock notices.

Budget policy: FIX the hot spot, never raise the budget (log what was
optimized in DECISIONS.md).
"""

import time

import pytest

from app.services.proforma import engine, leases

WALL_CLOCK_BUDGET_SECONDS = 2.0  # hard cap per the spec
LEASE_INCOME_CALL_BUDGET = 4  # main (extended) + stabilized window + headroom

_RECOVERY_CYCLE = ["NNN", "base_year_stop", "fixed_psf", "gross"]
_ESCALATION_CYCLE = [("fixed_pct", 0.03), ("fixed_step", 0.75), ("none", 0)]


def fifty_lease_deal() -> dict:
    """Deterministic 50-tenant office roll: starts staggered from 2023
    (pre-epoch escalation anniversaries), expiries laddered across the
    10-year hold so rollover generations fire throughout."""
    lease_rows = []
    for i in range(50):
        start_year = 2023 + (i % 4)
        start_month = (i % 12) + 1
        end_year = 2026 + (i % 9)  # expiries from 2026..2034
        end_month = ((i * 5) % 12) + 1
        recovery = _RECOVERY_CYCLE[i % 4]
        esc_type, esc_value = _ESCALATION_CYCLE[i % 3]
        lease_rows.append({
            "tenant": f"Tenant {i + 1:02d}",
            "suiteId": f"{100 + i}",
            "sf": 1_000 + (i % 7) * 350,
            "startDate": f"{start_year}-{start_month:02d}-01",
            "endDate": f"{end_year}-{end_month:02d}-28",
            "baseRentPsfAnnual": 28 + (i % 10),
            "escalationType": esc_type,
            "escalationValue": esc_value,
            "escalationMonths": 12,
            "recoveryType": recovery,
            "recoveryValue": 5.5 if recovery == "fixed_psf" else 0,
            "freeRentMonths": i % 3,
        })
    return {
        "dealType": "acquisition",
        "propertyType": "office",
        "purchasePrice": 60_000_000,
        "closingCostsPct": 0.01,
        "holdPeriodYears": 10,
        "exitCapRatePct": 0.065,
        "costOfSalePct": 0.02,
        "discountRatePct": 0.10,
        "commercialLeases": lease_rows,
        "renewalProbability": 0.65,
        "downtimeMonths": 6,
        "marketRentPsf": 34,
        "marketRentGrowthPct": 0.03,
        "newTermYears": 5,
        "tiNewPsf": 35,
        "tiRenewalPsf": 10,
        "lcNewPct": 0.06,
        "lcRenewalPct": 0.03,
        "realEstateTaxes": 900_000,
        "insurance": 250_000,
        "utilities": 400_000,
        "repairsMaintenance": 300_000,
        "managementFeePct": 0.03,
        "creditLossPct": 0.01,
        "rentGrowthMode": "per_year", "rentGrowthPct": 0.03,
        "expenseGrowthMode": "per_year", "expenseGrowthPct": 0.025,
        "ltvOrLtc": 0.6, "interestRate": 0.065, "amortYears": 30,
        "loanTermYears": 10, "ioMonths": 24, "originationFeePct": 0.01,
        "dscrConstraint": 1.25, "debtYieldConstraint": 0.08,
        "lpSplitPct": 0.9, "gpSplitPct": 0.1, "preferredReturnPct": 0.08,
        "waterfallTiers": [],
    }


def test_fifty_lease_roll_computes_inside_the_budget():
    deal = fifty_lease_deal()
    engine.compute(deal)  # warm-up: imports, first-touch allocations

    start = time.perf_counter()
    result = engine.compute(deal)
    elapsed = time.perf_counter() - start

    # Sanity: the fixture actually exercised the machinery.
    assert len(result["statement"]["leases"]["perLease"]) == 50
    assert sum(result["statement"]["leasingCapital"]) > 0  # rollovers fired
    assert result["outputs"]["leveredIrr"] is not None

    assert elapsed < WALL_CLOCK_BUDGET_SECONDS, (
        f"50-lease compute took {elapsed:.2f}s (budget "
        f"{WALL_CLOCK_BUDGET_SECONDS}s) — find the hot spot, don't raise "
        "the budget."
    )


def test_lease_income_is_built_a_constant_number_of_times(monkeypatch):
    """The call-count budget: build_lease_income must run O(1) times per
    compute, independent of lease count or grid length."""
    calls = {"n": 0}
    real = leases.build_lease_income

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(leases, "build_lease_income", counting)
    engine.compute(fifty_lease_deal())
    assert calls["n"] <= LEASE_INCOME_CALL_BUDGET, (
        f"build_lease_income ran {calls['n']} times in one compute "
        f"(budget {LEASE_INCOME_CALL_BUDGET}) — something is re-evaluating "
        "per lease/month."
    )
