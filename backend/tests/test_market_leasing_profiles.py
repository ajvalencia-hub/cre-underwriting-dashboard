"""Roadmap #27: market leasing profiles. A lease names a profile; the
profile's non-blank cells override the deal's rollover assumptions for that
lease only (ARGUS-style market leasing assumptions per space type).

Hand fixture: two 5,000 SF gross leases expiring 2026-12-31, market rent
$30 flat. Deal assumptions: renewal 0%, 12 months downtime. Tenant B uses
the "anchor" profile: renewal 100%, $40 market rent. So in 2027 A is dark
(its re-let path is vacant a full year) and B renews at $40.
"""

import pytest

from app.services.proforma import leases

POOL = [0.0] * 36


def _inputs(profile_b="anchor", **overrides) -> dict:
    lease = {
        "sf": 5_000, "startDate": "2025-01-01", "endDate": "2026-12-31",
        "baseRentPsfAnnual": 30, "escalationType": "none", "recoveryType": "gross",
    }
    inputs = {
        "commercialLeases": [
            {**lease, "tenant": "A", "suiteId": "A"},
            {**lease, "tenant": "B", "suiteId": "B", "leasingProfile": profile_b},
        ],
        "renewalProbability": 0,
        "downtimeMonths": 12,
        "marketRentPsf": 30,
        "marketRentGrowthPct": 0,
        "newTermYears": 5,
        "marketLeasingProfiles": [
            {"profileName": "Anchor", "renewalProbability": 1, "marketRentPsf": 40},
        ],
    }
    inputs.update(overrides)
    return inputs


def _income(inputs) -> dict:
    return leases.build_lease_income(inputs, 36, POOL, 0.0)


def test_a_profile_applies_only_to_the_leases_that_name_it():
    income = _income(_inputs())
    month_13 = 12  # January 2027
    by_suite = {row["suiteId"]: row for row in income["perLease"]}
    # A: deal assumptions — re-let path, vacant for the 12-month downtime.
    assert by_suite["A"]["downtimeLoss"][month_13] == pytest.approx(30 * 5_000 / 12)
    # B: the anchor profile — renews with no downtime at the profile's $40.
    assert by_suite["B"]["downtimeLoss"][month_13] == 0
    assert by_suite["B"]["scheduledRent"][month_13] == pytest.approx(40 * 5_000 / 12)
    assert by_suite["B"]["leasingProfile"] == "anchor"
    assert "leasingProfile" not in by_suite["A"]
    assert income["occupancy"][month_13] == pytest.approx(0.5)


def test_blank_profile_cells_keep_the_deal_assumption():
    # The profile sets renewal only; market rent stays the deal's $30.
    inputs = _inputs(marketLeasingProfiles=[{"profileName": "anchor", "renewalProbability": 1, "marketRentPsf": None}])
    by_suite = {row["suiteId"]: row for row in _income(inputs)["perLease"]}
    assert by_suite["B"]["scheduledRent"][12] == pytest.approx(30 * 5_000 / 12)
    assert by_suite["B"]["downtimeLoss"][12] == 0


def test_an_unknown_profile_falls_back_with_a_warning():
    income = _income(_inputs(profile_b="Retail inline"))
    by_suite = {row["suiteId"]: row for row in income["perLease"]}
    assert by_suite["B"]["downtimeLoss"][12] == pytest.approx(30 * 5_000 / 12)
    assert any("'Retail inline'" in w for w in income["warnings"])


def test_without_profiles_nothing_changes():
    plain = _inputs(profile_b="")
    plain.pop("marketLeasingProfiles")
    with_unused = _inputs(profile_b="")
    assert _income(plain) == _income(with_unused)


def test_occupancy_projection_follows_each_lease_profile():
    # The gross-up's occupancy projection must match the main loop (I3's
    # drift guard), now per lease.
    inputs = _inputs()
    income = _income(inputs)
    deal = leases._rollover_assumptions(inputs)
    profile = leases._rollover_assumptions(inputs, leases.leasing_profiles(inputs)["anchor"])
    rows = inputs["commercialLeases"]
    projected = leases._occupancy_projection(
        rows, deal, 36, 10_000, lambda lease: profile if lease.get("leasingProfile") else deal
    )
    assert projected == pytest.approx(income["occupancy"])
