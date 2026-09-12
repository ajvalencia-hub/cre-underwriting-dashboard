"""Run 6 wave 2 [FIN]: buildingRsf — the pro-rata recovery denominator (and
occupancy basis) for lease deals. Blank = listed-SF share (today); larger
than the listed SF = unlisted vacant suites' share of recoverable opex is
NOT billed to tenants; smaller = ignored with a warning."""

import json
from pathlib import Path

import pytest

from app.services.proforma import engine

CORPUS = Path(__file__).parent / "parity" / "corpus"


def nnn(**overrides) -> dict:
    deal = json.loads((CORPUS / "commercial_nnn" / "inputs.json").read_text())
    deal.update(overrides)
    return deal


def test_blank_building_rsf_is_byte_identical():
    base = engine.compute(nnn())
    assert engine.compute(nnn(buildingRsf=None)) == base
    assert engine.compute(nnn(buildingRsf=0)) == base
    assert "buildingRsf" not in base["statement"]["leases"]


def test_building_rsf_above_listed_sf_reduces_recoveries_pro_rata():
    base = engine.compute(nnn())
    listed_sf = sum(lease["sf"] for lease in nnn()["commercialLeases"])
    bigger = engine.compute(nnn(buildingRsf=listed_sf * 1.25))
    stmt_base, stmt = base["statement"], bigger["statement"]
    exit_month = stmt["exitMonth"]
    for m in range(1, exit_month + 1):
        # Single NNN tenant: share drops from 1.0 to 0.8 of the pool.
        assert stmt["recoveries"][m] == pytest.approx(0.8 * stmt_base["recoveries"][m])
        # Recoveries ride otherIncome; base rent (GPR) is untouched.
        assert stmt["gpr"][m] == pytest.approx(stmt_base["gpr"][m])
        assert stmt["otherIncome"][m] == pytest.approx(
            stmt_base["otherIncome"][m] - 0.2 * stmt_base["recoveries"][m]
        )
        # Physical occupancy is measured over the whole building.
        assert stmt["occupancy"][m] == pytest.approx(0.8 * stmt_base["occupancy"][m])
    assert stmt["leases"]["buildingRsf"] == pytest.approx(listed_sf * 1.25)
    assert stmt["leases"]["totalSf"] == pytest.approx(listed_sf)  # listed SF is reported as-is
    # NOI (and therefore every return) falls by the unrecovered share.
    assert bigger["outputs"]["leveredIrr"] < base["outputs"]["leveredIrr"]
    assert not any("buildingRsf" in w for w in bigger["warnings"])


def test_building_rsf_below_listed_sf_is_ignored_with_warning():
    base = engine.compute(nnn())
    smaller = engine.compute(nnn(buildingRsf=100))
    assert smaller["statement"]["recoveries"] == base["statement"]["recoveries"]
    assert smaller["statement"]["occupancy"] == base["statement"]["occupancy"]
    assert smaller["outputs"] == base["outputs"]
    assert "buildingRsf" not in smaller["statement"]["leases"]
    assert any(
        "buildingRsf" in w and "below the listed lease SF" in w for w in smaller["warnings"]
    )


def test_building_rsf_equal_to_listed_sf_changes_nothing_but_reports_it():
    base = engine.compute(nnn())
    listed_sf = sum(lease["sf"] for lease in nnn()["commercialLeases"])
    same = engine.compute(nnn(buildingRsf=listed_sf))
    assert same["outputs"] == base["outputs"]
    assert same["statement"]["recoveries"] == base["statement"]["recoveries"]
    assert same["statement"]["leases"]["buildingRsf"] == pytest.approx(listed_sf)
