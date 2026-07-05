"""I8: per-lease drill-down — the slices are the SAME numbers the property
aggregate is built from (sum identity), keyed by suiteId, exposed through
the ?detail=true statement and trimmed to the hold horizon."""

import json
from pathlib import Path

import pytest

from app.services.proforma import engine, leases

FIXTURES = Path(__file__).parent.parent / "tests" / "regression" / "fixtures"


@pytest.fixture
def rollover_deal() -> dict:
    return json.loads((FIXTURES / "commercial_rollover.json").read_text())


_PAIRS = [
    ("scheduledRent", "scheduledBaseRent"),
    ("freeRent", "freeRentLoss"),
    ("downtimeLoss", "downtimeLoss"),
    ("recoveries", "recoveries"),
    ("leasingCapital", "leasingCapital"),
]


def test_per_lease_slices_sum_to_property_vectors(rollover_deal):
    months = 72
    income = leases.build_lease_income(
        rollover_deal, months, [1_000.0] * months, 0.025
    )
    slices = income["perLease"]
    assert [s["suiteId"] for s in slices] == ["100", "200"]
    for slice_key, property_key in _PAIRS:
        for m in range(months):
            total = sum(s[slice_key][m] for s in slices)
            assert total == pytest.approx(income[property_key][m], abs=1e-9), (
                slice_key, m,
            )


def test_statement_exposes_slices_keyed_and_trimmed(rollover_deal):
    result = engine.compute(rollover_deal)
    per_lease = result["statement"]["leases"]["perLease"]
    total = len(result["statement"]["months"]) - 1  # index 0 = close
    by_suite = {s["suiteId"]: s for s in per_lease}
    assert set(by_suite) == {"100", "200"}
    for entry in per_lease:
        for key, _ in _PAIRS:
            assert len(entry[key]) == total  # trimmed: no forward window
    # Alpha (suite 100) expires month 30 -> a rollover generation exists,
    # with its capital landing inside the slice.
    alpha = by_suite["100"]
    assert alpha["rolloverEvents"], "expiring lease must carry rollover events"
    assert sum(alpha["leasingCapital"]) > 0
    # Beta (suite 200) runs past the hold: no rollover inside the horizon.
    assert by_suite["200"]["rolloverEvents"] == []
    assert sum(by_suite["200"]["leasingCapital"]) == pytest.approx(0)


def test_no_end_date_lease_still_gets_a_slice(rollover_deal):
    deal = json.loads(json.dumps(rollover_deal))
    deal["commercialLeases"][1].pop("endDate")
    income = leases.build_lease_income(deal, 60, [0.0] * 60, 0.0)
    assert len(income["perLease"]) == 2
    assert income["perLease"][1]["rolloverEvents"] == []
