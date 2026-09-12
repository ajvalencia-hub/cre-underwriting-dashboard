"""H1: lease-level commercial engine — hand-computed fixtures for every
escalation and recovery type, free rent, rollover blending at p=0/0.5/1,
base-year floors, and the engine-level integration. Analysis month 1 =
January 2026 (the documented epoch)."""

from pathlib import Path

import pytest

from app.services.proforma import engine, leases, operations
from app.services.proforma.timeline import Timeline

FIXTURES = Path(__file__).parent / "fixtures"

SF = 10_000.0
FLAT_RECOVERABLE = [5_000.0] * 240  # $60,000/yr of recoverable opex


def lease(**overrides) -> dict:
    base = {
        "tenant": "Acme", "suiteId": "100", "sf": SF,
        "startDate": "2026-01-01", "endDate": "2031-12-31",  # ends month 72
        "baseRentPsfAnnual": 30.0, "escalationType": "none",
        "escalationValue": 0, "escalationMonths": 12,
        "recoveryType": "NNN", "recoveryValue": 0, "freeRentMonths": 0,
    }
    base.update(overrides)
    return base


def build(leases_list, months=24, recoverable=None, growth=0.0, **rollover):
    inputs = {"commercialLeases": leases_list, **rollover}
    return leases.build_lease_income(
        inputs, months, recoverable or FLAT_RECOVERABLE[:months], growth
    )


def test_nnn_flat_lease():
    """$30psf x 10,000sf = $25,000/mo base; NNN single tenant recovers 100%
    of the $5,000/mo recoverable opex. No expiry inside the window."""
    result = build([lease()])
    assert result["scheduledBaseRent"][0] == pytest.approx(25_000)
    assert result["collectedBaseRent"][23] == pytest.approx(25_000)
    assert result["recoveries"][0] == pytest.approx(5_000)
    assert all(v == 0 for v in result["leasingCapital"])
    assert result["walt"] == pytest.approx(6.0)  # 72 months / 12
    assert result["occupancyYear1"] == pytest.approx(1.0)


def test_fixed_pct_escalation():
    """3%/yr on lease anniversaries: months 1-12 at $25,000, months 13-24 at
    25,000 x 1.03 = $25,750."""
    result = build([lease(escalationType="fixed_pct", escalationValue=0.03)])
    assert result["scheduledBaseRent"][0] == pytest.approx(25_000)
    assert result["scheduledBaseRent"][11] == pytest.approx(25_000)
    assert result["scheduledBaseRent"][12] == pytest.approx(25_750)
    assert result["scheduledBaseRent"][23] == pytest.approx(25_750)


def test_fixed_step_escalation():
    """+$1 psf/yr each anniversary: year 2 = $31psf -> 31 x 10,000/12."""
    result = build([lease(escalationType="fixed_step", escalationValue=1.0)])
    assert result["scheduledBaseRent"][12] == pytest.approx(31 * SF / 12)


def test_pre_epoch_start_counts_true_anniversaries():
    """A lease that started 2025-01-01 has its FIRST in-window escalation at
    Jan 2026 (month 1 is already elapsed-interval 1)."""
    result = build(
        [lease(startDate="2025-01-01", escalationType="fixed_pct", escalationValue=0.03)]
    )
    assert result["scheduledBaseRent"][0] == pytest.approx(25_000 * 1.03)


def test_free_rent_abates_base_only():
    """3 free months: no base rent collected, NNN recoveries still paid."""
    result = build([lease(freeRentMonths=3)])
    assert result["collectedBaseRent"][0] == 0
    assert result["freeRentLoss"][0] == pytest.approx(25_000)
    assert result["recoveries"][0] == pytest.approx(5_000)
    assert result["collectedBaseRent"][3] == pytest.approx(25_000)


def test_base_year_stop():
    """Base year = 2026 at $60,000; 5% growth -> 2027 = $63,000. Year-1
    recovery = 0; year-2 recovery = (63,000 - 60,000)/12 = $250/mo."""
    recoverable = [5_000 * 1.05 ** ((m - 1) // 12) for m in range(1, 25)]
    result = build([lease(recoveryType="base_year_stop")], recoverable=recoverable, growth=0.05)
    assert result["recoveries"][0] == pytest.approx(0)
    assert result["recoveries"][12] == pytest.approx(250)


def test_base_year_stop_never_negative_on_declining_opex():
    recoverable = [5_000 * 0.9 ** ((m - 1) // 12) for m in range(1, 25)]
    result = build([lease(recoveryType="base_year_stop")], recoverable=recoverable, growth=-0.10)
    assert all(v >= 0 for v in result["recoveries"])
    assert result["recoveries"][12] == pytest.approx(0)


def test_fixed_psf_and_gross_recoveries():
    fixed = build([lease(recoveryType="fixed_psf", recoveryValue=4.0)])
    assert fixed["recoveries"][0] == pytest.approx(4.0 * SF / 12)  # 3,333.33
    gross = build([lease(recoveryType="gross")])
    assert all(v == 0 for v in gross["recoveries"])


ROLLOVER = {
    "marketRentPsf": 36.0, "marketRentGrowthPct": 0.0, "downtimeMonths": 6,
    "newTermYears": 5, "tiNewPsf": 10.0, "tiRenewalPsf": 5.0,
    "lcNewPct": 0.06, "lcRenewalPct": 0.03,
}


def test_rollover_pure_relet():
    """p=0: expiry at month 12; TI = $10psf x 10,000 = $100,000 and LC =
    6% x ($36 x 10,000 x 5yrs) = $108,000, both in month 13; 6 months of
    downtime at zero collections; then $30,000/mo market rent."""
    result = build(
        [lease(endDate="2026-12-31", recoveryType="gross")],
        months=36, renewalProbability=0.0, **ROLLOVER,
    )
    assert result["leasingCapital"][12] == pytest.approx(100_000 + 108_000)
    assert result["collectedBaseRent"][12] == pytest.approx(0)  # month 13, downtime
    assert result["downtimeLoss"][12] == pytest.approx(30_000)
    assert result["collectedBaseRent"][18] == pytest.approx(30_000)  # month 19
    assert result["occupiedSf"][12] == pytest.approx(0)


def test_rollover_pure_renewal():
    """p=1: TI = $5psf x SF = $50,000, LC = 3% x (36 x SF x 5) = $54,000;
    no downtime — market rent collected from month 13."""
    result = build(
        [lease(endDate="2026-12-31", recoveryType="gross")],
        months=36, renewalProbability=1.0, **ROLLOVER,
    )
    assert result["leasingCapital"][12] == pytest.approx(50_000 + 54_000)
    assert result["collectedBaseRent"][12] == pytest.approx(30_000)
    assert result["downtimeLoss"][12] == pytest.approx(0)


def test_rollover_expected_blend_is_probability_weighted():
    p0 = build([lease(endDate="2026-12-31", recoveryType="gross")],
               months=36, renewalProbability=0.0, **ROLLOVER)
    p1 = build([lease(endDate="2026-12-31", recoveryType="gross")],
               months=36, renewalProbability=1.0, **ROLLOVER)
    blended = build([lease(endDate="2026-12-31", recoveryType="gross")],
                    months=36, renewalProbability=0.6, **ROLLOVER)
    for vec in ("collectedBaseRent", "leasingCapital", "downtimeLoss"):
        for m in range(36):
            expected = 0.6 * p1[vec][m] + 0.4 * p0[vec][m]
            assert blended[vec][m] == pytest.approx(expected, abs=1e-6), (vec, m)


def test_market_rent_fallback_is_escalated_in_place():
    """marketRentPsf unset: rollover rent = the lease's own escalated rent at
    expiry (30 x 1.03 after one anniversary), not zero."""
    result = build(
        [lease(endDate="2027-12-31", escalationType="fixed_pct", escalationValue=0.03,
               recoveryType="gross")],
        months=36, renewalProbability=1.0, downtimeMonths=0, marketRentGrowthPct=0.0,
    )
    assert result["collectedBaseRent"][24] == pytest.approx(25_000 * 1.03)


def test_three_tenant_expiry_schedule_and_vectors():
    """A: 1,000sf @ $12 ends 2026-12; B: 2,000sf @ $24 ends 2027-12;
    C: 3,000sf @ $12 ends 2028-12. p=0.5, downtime 2, TI new $10/renew $0,
    no LC, market = in-place fallback, growth 0.
    GPR month 1 = 1,000+4,000+3,000 = 8,000. A's downtime (months 13-14):
    collected = 0.5x1,000 + 4,000 + 3,000 = 7,500. TI month 13 =
    0.5 x 10 x 1,000 = 5,000; month 25 = 0.5 x 10 x 2,000 = 10,000."""
    tenants = [
        lease(tenant="A", sf=1_000, baseRentPsfAnnual=12, endDate="2026-12-31", recoveryType="gross"),
        lease(tenant="B", sf=2_000, baseRentPsfAnnual=24, endDate="2027-12-31", recoveryType="gross"),
        lease(tenant="C", sf=3_000, baseRentPsfAnnual=12, endDate="2028-12-31", recoveryType="gross"),
    ]
    result = build(
        tenants, months=36, renewalProbability=0.5, downtimeMonths=2,
        tiNewPsf=10.0, tiRenewalPsf=0.0, lcNewPct=0.0, lcRenewalPct=0.0,
        marketRentGrowthPct=0.0,
    )
    assert result["collectedBaseRent"][0] == pytest.approx(8_000)
    assert result["collectedBaseRent"][12] == pytest.approx(7_500)
    assert result["collectedBaseRent"][14] == pytest.approx(8_000)  # after A's downtime
    assert result["collectedBaseRent"][24] == pytest.approx(1_000 + 2_000 + 3_000)  # B downtime
    assert result["leasingCapital"][12] == pytest.approx(5_000)
    assert result["leasingCapital"][24] == pytest.approx(10_000)

    schedule = {row["year"]: row for row in result["expirationSchedule"]}
    assert schedule[2026]["sfExpiring"] == 1_000
    assert schedule[2026]["pctOfRent"] == pytest.approx(12_000 / 96_000)
    assert schedule[2027]["pctOfRent"] == pytest.approx(48_000 / 96_000)
    assert schedule[2028]["pctOfRent"] == pytest.approx(36_000 / 96_000)


# ------------------------------------------------------------- engine level

def _commercial_deal() -> dict:
    """NNN wash: recoveries exactly offset the recoverable taxes, so NOI =
    base rent = $300,000/yr on a $3,000,000 purchase -> 10% going-in cap."""
    return {
        "dealType": "acquisition", "propertyType": "retail",
        "purchasePrice": 3_000_000, "closingCostsPct": 0, "acquisitionFeePct": 0,
        "holdPeriodYears": 5, "exitCapRatePct": 0.08, "costOfSalePct": 0,
        "commercialLeases": [lease(endDate="2033-12-31")],  # beyond hold + 12mo
        "realEstateTaxes": 60_000, "managementFeePct": 0, "creditLossPct": 0,
        "rentGrowthMode": "flat", "expenseGrowthMode": "flat",
        "ltvOrLtc": 0, "lpSplitPct": 0.9, "gpSplitPct": 0.1,
        "preferredReturnPct": 0.08, "waterfallTiers": [],
    }


def test_engine_integration_nnn_wash():
    result = engine.compute(_commercial_deal())
    assert result["gprSource"] == "commercialLeases"
    assert result["outputs"]["goingInCapRate"] == pytest.approx(0.10, abs=1e-9)
    statement = result["statement"]
    # month 1: gpr = scheduled 25,000; recoveries in otherIncome; NOI 25,000
    assert statement["gpr"][1] == pytest.approx(25_000)
    assert statement["otherIncome"][1] == pytest.approx(5_000)
    assert statement["noi"][1] == pytest.approx(25_000)
    assert statement["leases"]["walt"] == pytest.approx(8.0)  # ends month 96
    assert statement["leases"]["occupancyYear1"] == pytest.approx(1.0)
    # terminal: flat 300k forward NOI at 8% cap
    assert result["outputs"]["terminalValue"] == pytest.approx(300_000 / 0.08)


def test_engine_leasing_capital_hits_cash_flows_not_noi():
    deal = _commercial_deal()
    deal["commercialLeases"] = [lease(endDate="2027-12-31")]  # expires month 24
    deal.update({
        "renewalProbability": 0.0, "downtimeMonths": 0, "marketRentPsf": 30.0,
        "marketRentGrowthPct": 0.0, "newTermYears": 10, "tiNewPsf": 20.0,
    })
    result = engine.compute(deal)
    statement = result["statement"]
    ti = 20.0 * SF  # 200,000 at month 25
    assert statement["leasingCapital"][25] == pytest.approx(ti)
    # NOI is untouched by TI; levered CF in that month drops by exactly TI.
    assert statement["noi"][25] == pytest.approx(25_000)
    assert statement["levered"][25] == pytest.approx(statement["noi"][25] - ti)


def test_operations_stabilized_noi_uses_in_place_leases():
    deal = _commercial_deal()
    assert operations.stabilized_annual_noi(deal) == pytest.approx(300_000)


def test_timeline_zeroing_under_construction():
    deal = _commercial_deal()
    deal.update({"dealType": "development", "landCost": 500_000, "hardCosts": 2_000_000,
                 "constructionMonths": 6, "ltvOrLtc": 0})
    ops = operations.build_noi_vector(deal, Timeline(24, 6, 0, 7))
    assert all(v == 0 for v in ops["noi"][:6])
    assert ops["noi"][6] == pytest.approx(25_000)
