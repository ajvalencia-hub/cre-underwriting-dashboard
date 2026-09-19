"""Lease-roll deals (roadmap #10): general vacancy on top of rollover
downtime, and free rent on speculative (new / renewal) leases. Before,
a well-leased building had zero vacancy and re-leased space had no
concessions, overstating NOI and exit value."""

import json
from pathlib import Path

import pytest

from app.services.proforma import engine

_CORPUS = Path(__file__).parent / "parity" / "corpus"


@pytest.fixture
def nnn():
    # One NNN tenant, $30/sf on 10,000 sf, recoveries wash $60k taxes.
    data = json.loads((_CORPUS / "commercial_nnn" / "inputs.json").read_text())
    data.pop("_comment", None)
    return data


def test_general_vacancy_takes_its_share_of_rent_and_recoveries(nnn):
    base = engine.compute(nnn)["statement"]
    with_gv = engine.compute(dict(nnn, leaseGeneralVacancyPct=0.05))["statement"]
    # Month 1: rent 25,000 + recoveries 5,000 -> 5% = 1,500 of vacancy.
    assert with_gv["vacancyLoss"][1] - base["vacancyLoss"][1] == pytest.approx(1_500)
    assert base["noi"][1] - with_gv["noi"][1] == pytest.approx(1_500)


def test_general_vacancy_is_not_added_where_rollover_downtime_already_exceeds_it(nnn):
    # Lease expires inside the hold: all-re-let (p = 0) with 6 months of
    # downtime -> those months are 100% vacant, so no general vacancy on top.
    deal = json.loads(json.dumps(nnn))
    deal["commercialLeases"][0]["endDate"] = "2027-12-31"
    deal.update(renewalProbability=0, downtimeMonths=6, marketRentPsf=30, newTermYears=5)
    base = engine.compute(deal)["statement"]
    with_gv = engine.compute(dict(deal, leaseGeneralVacancyPct=0.05))["statement"]
    downtime_month = 25  # first month after the Dec-2027 expiry
    assert with_gv["vacancyLoss"][downtime_month] == pytest.approx(base["vacancyLoss"][downtime_month])
    assert with_gv["vacancyLoss"][1] > base["vacancyLoss"][1]


def test_new_lease_free_rent_follows_the_downtime(nnn):
    deal = json.loads(json.dumps(nnn))
    deal["commercialLeases"][0]["endDate"] = "2027-12-31"
    deal.update(renewalProbability=0, downtimeMonths=3, marketRentPsf=30, newTermYears=5,
                marketRentGrowthPct=0, freeRentMonthsNew=2)
    stmt = engine.compute(deal)["statement"]
    monthly_rent = 30 * 10_000 / 12  # 25,000
    # Months 25-27 downtime; 28-29 free (tenant in place, no base rent); 30 pays.
    base_rent_collected = [stmt["gpr"][m] - stmt["vacancyLoss"][m] for m in range(24, 32)]
    assert base_rent_collected == pytest.approx([monthly_rent, 0, 0, 0, 0, 0, monthly_rent, monthly_rent])


def test_renewal_free_rent_is_probability_weighted(nnn):
    deal = json.loads(json.dumps(nnn))
    deal["commercialLeases"][0]["endDate"] = "2027-12-31"
    deal.update(renewalProbability=0.5, downtimeMonths=0, marketRentPsf=30, newTermYears=5,
                marketRentGrowthPct=0, freeRentMonthsRenewal=1)
    stmt = engine.compute(deal)["statement"]
    # Month 25: half the expected rent is a renewal in its free month.
    assert stmt["vacancyLoss"][25] == pytest.approx(0.5 * 25_000)
    assert stmt["vacancyLoss"][26] == pytest.approx(0)


def test_all_zero_by_default(nnn):
    assert engine.compute(nnn)["outputs"] == engine.compute(
        dict(nnn, leaseGeneralVacancyPct=0, freeRentMonthsNew=0, freeRentMonthsRenewal=0)
    )["outputs"]
