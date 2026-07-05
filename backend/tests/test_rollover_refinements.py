"""I2: rollover refinements — split TI/LC timing (opt-in) and the renewal
rent spread.

Hand fixture: one 4,000 SF tenant at $30 gross, expiring month 12
(2026-12-31); market $30 flat (growth 0), downtime 4, TI new $20 / renewal
$5 psf, LC new 6% / renewal 3% of first-year-rent x 5-yr term. Analysis 36
months. Generation 1 starts month 13; commencement = month 17.

Capital arithmetic (annual rent base 30 x 4,000 x 5yr = 600,000):
  renewal side = p x (5x4000  + 0.03x600,000) = p x 38,000
  re-let  side = (1-p) x (20x4000 + 0.06x600,000) = (1-p) x 116,000
"""

import pytest

from app.services.proforma import engine, leases


def roll_deal(**overrides) -> dict:
    deal = {
        "commercialLeases": [{
            "tenant": "T", "suiteId": "1", "sf": 4_000,
            "startDate": "2026-01-01", "endDate": "2026-12-31",
            "baseRentPsfAnnual": 30, "escalationType": "none",
            "recoveryType": "gross", "freeRentMonths": 0,
        }],
        "renewalProbability": 0.6, "downtimeMonths": 4,
        "marketRentPsf": 30, "marketRentGrowthPct": 0,
        "newTermYears": 5,
        "tiNewPsf": 20, "tiRenewalPsf": 5,
        "lcNewPct": 0.06, "lcRenewalPct": 0.03,
    }
    deal.update(overrides)
    return deal


def _capital(inputs: dict, months: int = 36) -> list[float]:
    return leases.build_lease_income(inputs, months, [0.0] * months, 0.0)["leasingCapital"]


RENEWAL_FULL = 5 * 4_000 + 0.03 * 600_000   # 38,000
RELET_FULL = 20 * 4_000 + 0.06 * 600_000    # 116,000


def test_split_timing_lands_capital_in_both_months_with_weights():
    capital = _capital(roll_deal(reletCapitalAtCommencement=True))
    assert capital[12] == pytest.approx(0.6 * RENEWAL_FULL)   # month 13: renewal side
    assert capital[16] == pytest.approx(0.4 * RELET_FULL)     # month 17: commencement
    assert sum(1 for c in capital if c > 0) == 2


def test_p_extremes_collapse_to_single_entry_timing():
    pure_renewal = _capital(roll_deal(reletCapitalAtCommencement=True, renewalProbability=1))
    assert pure_renewal[12] == pytest.approx(RENEWAL_FULL)
    assert sum(1 for c in pure_renewal if c > 0) == 1

    pure_relet = _capital(roll_deal(reletCapitalAtCommencement=True, renewalProbability=0))
    assert pure_relet[16] == pytest.approx(RELET_FULL)
    assert sum(1 for c in pure_relet if c > 0) == 1


def test_relet_commencement_past_horizon_is_not_incurred():
    """Expiry month 34, downtime 4 -> commencement month 39 > 36: the re-let
    capital simply never lands; the renewal side (month 35) still does."""
    deal = roll_deal(reletCapitalAtCommencement=True)
    deal["commercialLeases"][0]["endDate"] = "2028-10-31"  # month 34
    capital = _capital(deal)
    assert capital[34] == pytest.approx(0.6 * RENEWAL_FULL)  # month 35
    assert sum(capital) == pytest.approx(0.6 * RENEWAL_FULL)


def test_legacy_timing_is_the_default_and_totals_match():
    legacy = _capital(roll_deal())
    split = _capital(roll_deal(reletCapitalAtCommencement=True))
    # Default: ONE entry at expiry+1 carrying both sides.
    assert legacy[12] == pytest.approx(0.6 * RENEWAL_FULL + 0.4 * RELET_FULL)
    assert sum(1 for c in legacy if c > 0) == 1
    # Same dollars, different timing (flat market keeps LC bases equal).
    assert sum(legacy) == pytest.approx(sum(split))


def test_renewal_spread_changes_renewal_side_only():
    # p=1 (all renewal): rent and LC base scale with the spread.
    at_market = leases.build_lease_income(
        roll_deal(renewalProbability=1), 36, [0.0] * 36, 0.0
    )
    discounted = leases.build_lease_income(
        roll_deal(renewalProbability=1, renewalRentPsfDiscountPct=0.95), 36, [0.0] * 36, 0.0
    )
    # Post-rollover months: renewal rent = 95% of market.
    assert discounted["collectedBaseRent"][20] == pytest.approx(
        0.95 * at_market["collectedBaseRent"][20]
    )
    # LC base is spread-adjusted; TI is not.
    lc_at, lc_disc = 0.03 * 600_000, 0.03 * 0.95 * 600_000
    assert at_market["leasingCapital"][12] == pytest.approx(5 * 4_000 + lc_at)
    assert discounted["leasingCapital"][12] == pytest.approx(5 * 4_000 + lc_disc)

    # p=0 (all re-let): the spread changes NOTHING.
    base = leases.build_lease_income(roll_deal(renewalProbability=0), 36, [0.0] * 36, 0.0)
    spread = leases.build_lease_income(
        roll_deal(renewalProbability=0, renewalRentPsfDiscountPct=0.95), 36, [0.0] * 36, 0.0
    )
    for key in ("scheduledBaseRent", "collectedBaseRent", "downtimeLoss", "leasingCapital"):
        assert spread[key] == pytest.approx(base[key])


def test_downtime_window_cash_improves_with_split_timing():
    """Directional: deferring the re-let TI/LC out of expiry+1 raises the
    levered cash flow in that month (capital is below NOI, so DSCR itself
    is unchanged — cash timing is the point)."""
    base_deal = {
        "dealType": "acquisition", "propertyType": "retail",
        "purchasePrice": 2_000_000, "closingCostsPct": 0, "acquisitionFeePct": 0,
        "holdPeriodYears": 3, "exitCapRatePct": 0.07, "costOfSalePct": 0,
        "realEstateTaxes": 0, "managementFeePct": 0,
        "vacancyPct": 0, "creditLossPct": 0, "otherIncome": 0,
        "rentGrowthMode": "flat", "expenseGrowthMode": "flat",
        "ltvOrLtc": 0.5, "loanAmount": 1_000_000, "interestRate": 0.06,
        "amortYears": 30, "ioMonths": 36, "originationFeePct": 0,
        "dscrConstraint": 0, "debtYieldConstraint": 0,
        "lpSplitPct": 0.9, "gpSplitPct": 0.1, "preferredReturnPct": 0.08,
        "waterfallTiers": [],
        **roll_deal(),
    }
    legacy = engine.compute(base_deal)
    split = engine.compute({**base_deal, "reletCapitalAtCommencement": True})
    # Statement month 13 (expiry+1): levered CF strictly higher with split timing.
    assert split["statement"]["levered"][13] > legacy["statement"]["levered"][13]
    # ...and the deferred capital shows up at commencement instead.
    assert split["statement"]["leasingCapital"][17] > 0
    assert legacy["statement"]["leasingCapital"][17] == pytest.approx(0)


def test_defaults_reproduce_run3():
    plain = _capital(roll_deal())
    explicit = _capital(
        roll_deal(renewalRentPsfDiscountPct=1.0, reletCapitalAtCommencement=False)
    )
    assert plain == pytest.approx(explicit)
