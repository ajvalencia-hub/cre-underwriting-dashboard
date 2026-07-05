"""I1: CAM admin fee + management-fee recoverability.

Hand fixture: one NNN tenant, 5,000 SF (sole tenant -> share = 1),
$20 psf ($8,333.33/mo collected), recoverable taxes $36,000/yr
($3,000/mo pool), credit loss 0, flat growth, mgmt fee 3% of EGI.
"""

import pytest

from app.services.proforma import engine, operations
from app.services.proforma.timeline import Timeline


def nnn_deal(**overrides) -> dict:
    deal = {
        "dealType": "acquisition", "propertyType": "retail",
        "purchasePrice": 2_000_000, "closingCostsPct": 0, "acquisitionFeePct": 0,
        "holdPeriodYears": 5, "exitCapRatePct": 0.07, "costOfSalePct": 0,
        "commercialLeases": [{
            "tenant": "Solo", "suiteId": "1", "sf": 5_000,
            "startDate": "2026-01-01", "endDate": "2033-12-31",
            "baseRentPsfAnnual": 20, "escalationType": "none",
            "recoveryType": "NNN", "freeRentMonths": 0,
        }],
        "realEstateTaxes": 36_000, "managementFeePct": 0,
        "vacancyPct": 0, "creditLossPct": 0, "otherIncome": 0,
        "rentGrowthMode": "flat", "expenseGrowthMode": "flat",
        "ltvOrLtc": 0, "lpSplitPct": 0.9, "gpSplitPct": 0.1,
        "preferredReturnPct": 0.08, "waterfallTiers": [],
    }
    deal.update(overrides)
    return deal


def _month1(inputs: dict) -> dict:
    ops = operations.build_noi_vector(inputs, Timeline(12, 0, 0, 1))
    return {k: (v[0] if isinstance(v, list) and v else v) for k, v in ops.items()}


def test_admin_fee_marks_up_nnn_recoveries():
    base = _month1(nnn_deal())
    assert base["recoveries"] == pytest.approx(3_000)  # 36,000/12, share 1

    marked = _month1(nnn_deal(adminFeePct=0.10))
    assert marked["recoveries"] == pytest.approx(3_300)  # 3,000 x 1.10
    # NOI rises by exactly the markup (expenses unchanged).
    assert marked["noi"] - base["noi"] == pytest.approx(300)


def test_admin_fee_leaves_fixed_psf_and_gross_alone():
    fixed = nnn_deal(adminFeePct=0.10)
    fixed["commercialLeases"][0].update({"recoveryType": "fixed_psf", "recoveryValue": 6})
    assert _month1(fixed)["recoveries"] == pytest.approx(5_000 * 6 / 12)  # stated $psf, no markup

    gross = nnn_deal(adminFeePct=0.10)
    gross["commercialLeases"][0]["recoveryType"] = "gross"
    assert _month1(gross)["recoveries"] == pytest.approx(0)


def test_admin_fee_applies_to_base_year_delta_only():
    """Base-year stop with 4% expense growth: year-2 delta is billed WITH
    the markup, but the base comparison itself is on raw pool amounts."""
    deal = nnn_deal(adminFeePct=0.10, expenseGrowthMode="per_year", expenseGrowthPct=0.04)
    deal["commercialLeases"][0]["recoveryType"] = "base_year_stop"
    ops = operations.build_noi_vector(deal, Timeline(24, 0, 0, 1))
    assert ops["recoveries"][0] == pytest.approx(0)  # base year: no delta, no markup
    # Year 2: pool 36,000 x 1.04, delta 1,440/yr -> 120/mo -> x1.1 = 132.
    assert ops["recoveries"][12] == pytest.approx(1_440 / 12 * 1.10)


def test_mgmt_fee_joins_pool_on_pre_recovery_egi():
    """Fee 3%: pre-recovery EGI = collected 8,333.33 -> pool contribution
    250/mo; recoveries = 3,000 + 250 = 3,250. The fee EXPENSE stays on full
    EGI (which now includes the larger recoveries)."""
    result = _month1(nnn_deal(managementFeePct=0.03, mgmtFeeRecoverable=True))
    assert result["recoveries"] == pytest.approx(3_250)
    collected = 5_000 * 20 / 12
    egi = collected + 3_250
    assert result["managementFee"] == pytest.approx(egi * 0.03)

    # Flag off: pool unchanged even with a fee present.
    off = _month1(nnn_deal(managementFeePct=0.03))
    assert off["recoveries"] == pytest.approx(3_000)


def test_mgmt_recovery_cap():
    """Cap 1% of pre-recovery EGI: contribution min(250, 83.33) = 83.33."""
    result = _month1(
        nnn_deal(managementFeePct=0.03, mgmtFeeRecoverable=True, mgmtRecoveryCapPct=0.01)
    )
    pre_egi = 5_000 * 20 / 12
    assert result["recoveries"] == pytest.approx(3_000 + 0.01 * pre_egi)


def test_mgmt_in_pool_creates_no_spurious_base_year_step():
    """A base-year lease signed under the flag: flat growth means the mgmt
    dollars sit in BOTH the base year and every comparison year — recovery
    stays zero."""
    deal = nnn_deal(managementFeePct=0.03, mgmtFeeRecoverable=True)
    deal["commercialLeases"][0]["recoveryType"] = "base_year_stop"
    ops = operations.build_noi_vector(deal, Timeline(24, 0, 0, 1))
    assert all(r == pytest.approx(0, abs=1e-9) for r in ops["recoveries"])


def test_defaults_reproduce_run3_exactly():
    plain = engine.compute(nnn_deal(managementFeePct=0.03))
    explicit = engine.compute(
        nnn_deal(
            managementFeePct=0.03,
            adminFeePct=0,
            mgmtFeeRecoverable=False,
            mgmtRecoveryCapPct=None,
        )
    )
    assert plain["outputs"] == explicit["outputs"]
