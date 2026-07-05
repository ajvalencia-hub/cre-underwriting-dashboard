"""F5: golden-file tests over the deterministic extraction pipeline.

Each synthetic fixture (built fresh per run by tests/extraction_corpus/
builders.py) runs through the real parsing path; the full structured result
is compared against a checked-in golden JSON. Regenerate intentionally with:

    UPDATE_GOLDEN=1 python -m pytest tests/test_extraction_golden.py

A mismatch prints a unified diff of the two JSON documents.
"""

import difflib
import json
import os
from pathlib import Path

import pytest

from app.services.extraction import excel_extractor, pdf_extractor, rent_roll_parser, t12_parser
from app.services.extraction_service import _grid_from_pdf_tables
from tests.extraction_corpus import builders

GOLDEN_DIR = Path(__file__).parent / "extraction_corpus" / "golden"


def _rounded(obj):
    """Round floats to 6dp recursively so goldens are platform-stable."""
    if isinstance(obj, float):
        return round(obj, 6)
    if isinstance(obj, dict):
        return {k: _rounded(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rounded(v) for v in obj]
    return obj


def check_golden(name: str, actual: dict) -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    path = GOLDEN_DIR / f"{name}.json"
    actual_json = json.dumps(_rounded(actual), indent=2, sort_keys=True) + "\n"

    if os.environ.get("UPDATE_GOLDEN") == "1":
        path.write_text(actual_json)
        return

    if not path.exists():
        pytest.fail(f"Golden file missing: {path}. Seed it with UPDATE_GOLDEN=1.")

    expected_json = path.read_text()
    if actual_json != expected_json:
        diff = "\n".join(
            difflib.unified_diff(
                expected_json.splitlines(),
                actual_json.splitlines(),
                fromfile=f"golden/{name}.json",
                tofile="actual",
                lineterm="",
            )
        )
        pytest.fail(f"Golden mismatch for {name}:\n{diff}")


def test_yardi_rent_roll_golden(tmp_path):
    path = tmp_path / "yardi_rent_roll.xlsx"
    builders.build_yardi_rent_roll(path)
    grid = excel_extractor.extract_grid(path, "xlsx")
    parsed = rent_roll_parser.parse_rows(grid["headers"], grid["rows"], "yardi_rent_roll.xlsx", grid["sheet"])
    aggregates = rent_roll_parser.aggregate_multifamily(parsed["rows"])
    check_golden(
        "yardi_rent_roll",
        {
            "headerRowIndex": grid["headerRowIndex"],
            "matchedFields": sorted(parsed["matchedFields"]),
            "confidence": parsed["confidence"],
            "rows": parsed["rows"],
            "aggregates": aggregates,
        },
    )


def test_yardi_t12_golden(tmp_path):
    path = tmp_path / "yardi_t12.xlsx"
    builders.build_yardi_t12(path)
    grid = excel_extractor.extract_grid(path, "xlsx")
    parsed = t12_parser.parse_t12(grid["headers"], grid["rows"], "yardi_t12.xlsx", grid["sheet"])
    aggregates = t12_parser.aggregate_categories(parsed["lineItems"])
    check_golden(
        "yardi_t12",
        {
            "periodType": parsed["periodType"],
            "monthHeaders": parsed["monthHeaders"],
            "confidence": parsed["confidence"],
            "lineItems": parsed["lineItems"],
            "aggregates": aggregates,
        },
    )


def test_realpage_rent_roll_golden(tmp_path):
    path = tmp_path / "realpage_rent_roll.xlsx"
    builders.build_realpage_rent_roll(path)
    grid = excel_extractor.extract_grid(path, "xlsx")
    parsed = rent_roll_parser.parse_rows(grid["headers"], grid["rows"], "realpage_rent_roll.xlsx", grid["sheet"])
    aggregates = rent_roll_parser.aggregate_multifamily(parsed["rows"])
    check_golden(
        "realpage_rent_roll",
        {
            "headerRowIndex": grid["headerRowIndex"],
            "matchedFields": sorted(parsed["matchedFields"]),
            "confidence": parsed["confidence"],
            "rows": parsed["rows"],
            "aggregates": aggregates,
        },
    )


def test_broker_om_pdf_golden(tmp_path):
    path = tmp_path / "broker_om.pdf"
    builders.build_broker_om_pdf(path)
    pdf_data = pdf_extractor.extract_pdf(path)
    grid, table_warnings = _grid_from_pdf_tables(pdf_data["pages"])
    assert grid is not None
    parsed = rent_roll_parser.parse_rows(grid["headers"], grid["rows"], "broker_om.pdf", grid["sheet"])
    check_golden(
        "broker_om_pdf",
        {
            "pageCount": len(pdf_data["pages"]),
            "scanned": pdf_data["scanned"],
            "mergedSheet": grid["sheet"],
            "tableWarnings": table_warnings,
            "matchedFields": sorted(parsed["matchedFields"]),
            "rows": parsed["rows"],
        },
    )


def test_commercial_rent_roll_golden(tmp_path):
    path = tmp_path / "commercial_rent_roll.xlsx"
    builders.build_commercial_rent_roll(path)
    grid = excel_extractor.extract_grid(path, "xlsx")
    parsed = rent_roll_parser.parse_rows(
        grid["headers"], grid["rows"], "commercial_rent_roll.xlsx", grid["sheet"]
    )
    proposal = rent_roll_parser.propose_commercial_leases(parsed["rows"])
    check_golden(
        "commercial_rent_roll",
        {
            "matchedFields": sorted(parsed["matchedFields"]),
            "rows": parsed["rows"],
            "leaseProposal": proposal,
        },
    )


def test_costar_rent_roll_golden(tmp_path):
    path = tmp_path / "costar_rent_roll.xlsx"
    builders.build_costar_rent_roll(path)
    grid = excel_extractor.extract_grid(path, "xlsx")
    parsed = rent_roll_parser.parse_rows(
        grid["headers"], grid["rows"], "costar_rent_roll.xlsx", grid["sheet"]
    )
    proposal = rent_roll_parser.propose_commercial_leases(parsed["rows"])
    check_golden(
        "costar_rent_roll",
        {
            "matchedFields": sorted(parsed["matchedFields"]),
            "rows": parsed["rows"],
            "leaseProposal": proposal,
        },
    )


def test_costar_hostile_golden(tmp_path):
    path = tmp_path / "costar_hostile.xlsx"
    builders.build_costar_rent_roll_hostile(path)
    grid = excel_extractor.extract_grid(path, "xlsx")
    parsed = rent_roll_parser.parse_rows(
        grid["headers"], grid["rows"], "costar_hostile.xlsx", grid["sheet"]
    )
    proposal = rent_roll_parser.propose_commercial_leases(parsed["rows"])
    check_golden(
        "costar_hostile",
        {
            "matchedFields": sorted(parsed["matchedFields"]),
            "rows": parsed["rows"],
            "leaseProposal": proposal,
        },
    )


def test_stacking_plan_golden(tmp_path):
    path = tmp_path / "stacking_plan.pdf"
    builders.build_stacking_plan_pdf(path)
    pdf_data = pdf_extractor.extract_pdf(path)
    grid, table_warnings = _grid_from_pdf_tables(pdf_data["pages"])
    assert grid is not None
    parsed = rent_roll_parser.parse_rows(
        grid["headers"], grid["rows"], "stacking_plan.pdf", grid["sheet"]
    )
    proposal = rent_roll_parser.propose_commercial_leases(parsed["rows"])
    check_golden(
        "stacking_plan",
        {
            "tableWarnings": table_warnings,
            "matchedFields": sorted(parsed["matchedFields"]),
            "rows": parsed["rows"],
            "leaseProposal": proposal,
        },
    )


# ---------------------------------------------------------------------------
# Targeted assertions on the hostile details, independent of the golden blobs
# (so a bad regeneration can't silently bless a regression).
# ---------------------------------------------------------------------------


def test_costar_derivations(tmp_path):
    path = tmp_path / "costar.xlsx"
    builders.build_costar_rent_roll(path)
    grid = excel_extractor.extract_grid(path, "xlsx")
    parsed = rent_roll_parser.parse_rows(grid["headers"], grid["rows"], "costar.xlsx", grid["sheet"])
    by_suite = {r["unit"]: r for r in parsed["rows"]}

    # Monthly rent derives from the annual figure (197,600 / 12).
    assert by_suite["400"]["inPlaceRentMonthly"] == pytest.approx(16_466.67, abs=0.01)
    assert by_suite["400"]["rentDerivedFrom"] == "annualRent"
    # No annual figure -> derives from $/SF x SF (33.50 x 2,400 / 12).
    assert by_suite["210"]["inPlaceRentMonthly"] == pytest.approx(6_700)
    assert by_suite["210"]["rentDerivedFrom"] == "rentPsfAnnual"
    assert by_suite["400"]["floor"] == "4"

    proposal = rent_roll_parser.propose_commercial_leases(parsed["rows"])
    by_id = {p["suiteId"]: p for p in proposal["rows"]}
    # $/SF column wins over any derivation for the proposed base rent.
    assert by_id["400"]["baseRentPsfAnnual"] == pytest.approx(38.00)
    assert by_id["400"]["recoveryType"] == "gross"  # Full Service
    assert by_id["200"]["recoveryType"] == "NNN"
    assert by_id["210"]["recoveryType"] == "base_year_stop"  # Modified Gross


def test_costar_hostile_details(tmp_path):
    path = tmp_path / "hostile.xlsx"
    builders.build_costar_rent_roll_hostile(path)
    grid = excel_extractor.extract_grid(path, "xlsx")
    parsed = rent_roll_parser.parse_rows(grid["headers"], grid["rows"], "hostile.xlsx", grid["sheet"])
    proposal = rent_roll_parser.propose_commercial_leases(parsed["rows"])
    by_id = {p["suiteId"]: p for p in proposal["rows"]}

    # Month-year-only expiry reads as the LAST day of that month.
    assert by_id["150"]["endDate"] == "2027-06-30"
    assert by_id["Suites 100-102"]["endDate"] == "2028-06-30"
    # Monthly-magnitude rent converts normally: 4,500 x 12 / 1,800 = $30/SF.
    assert by_id["150"]["baseRentPsfAnnual"] == pytest.approx(30.00)
    # Annual-magnitude rent in the monthly column: 87,500/mo would imply
    # $420/SF/yr -> reinterpreted as annual = $35/SF, WITH a warning.
    assert by_id["Suites 100-102"]["baseRentPsfAnnual"] == pytest.approx(35.00)
    assert any("magnitude" in w.lower() for w in proposal["warnings"])
    # MTM: no expiry, called out by name.
    assert by_id["160"]["endDate"] is None
    assert any("month-to-month" in w.lower() for w in proposal["warnings"])
    # Combined suite range kept as one lease, warned.
    assert any("suite range" in w.lower() for w in proposal["warnings"])


def test_stacking_plan_details(tmp_path):
    path = tmp_path / "stack.pdf"
    builders.build_stacking_plan_pdf(path)
    pdf_data = pdf_extractor.extract_pdf(path)
    grid, _ = _grid_from_pdf_tables(pdf_data["pages"])
    parsed = rent_roll_parser.parse_rows(grid["headers"], grid["rows"], "stack.pdf", grid["sheet"])
    proposal = rent_roll_parser.propose_commercial_leases(parsed["rows"])
    by_id = {p["suiteId"]: p for p in proposal["rows"]}

    # Rents where stated come from the $/SF column...
    assert by_id["500"]["baseRentPsfAnnual"] == pytest.approx(31.50)
    # ...and occupied no-rent rows SURVIVE at $0 with a fill-in warning,
    # instead of silently vanishing.
    assert by_id["400"]["baseRentPsfAnnual"] == 0
    assert any("NO stated rent" in w for w in proposal["warnings"])
    # The vacant floor is skipped, not proposed at $0.
    assert "200" not in by_id
    # Month-year expiry on floor 3 reads as month end.
    assert by_id["300"]["endDate"] == "2029-03-31"


def test_commercial_lease_proposal_details(tmp_path):
    path = tmp_path / "crr.xlsx"
    builders.build_commercial_rent_roll(path)
    grid = excel_extractor.extract_grid(path, "xlsx")
    parsed = rent_roll_parser.parse_rows(grid["headers"], grid["rows"], "crr.xlsx", grid["sheet"])
    proposal = rent_roll_parser.propose_commercial_leases(parsed["rows"])

    by_tenant = {p["tenant"]: p for p in proposal["rows"]}
    assert set(by_tenant) == {"Blue Bagel LLC", "Verde Yoga", "Corner Dental"}
    # $6,000/mo x 12 / 2,400sf = $30 psf/yr
    assert by_tenant["Blue Bagel LLC"]["baseRentPsfAnnual"] == 30.0
    assert by_tenant["Blue Bagel LLC"]["recoveryType"] == "NNN"
    assert by_tenant["Verde Yoga"]["recoveryType"] == "gross"
    assert by_tenant["Corner Dental"]["recoveryType"] == "base_year_stop"
    assert by_tenant["Blue Bagel LLC"]["startDate"] == "2024-01-01"
    assert by_tenant["Blue Bagel LLC"]["endDate"] == "2028-12-31"
    # The vacant suite is skipped and named in a warning.
    assert any("vacant" in w.lower() or "VACANT" in w for w in proposal["warnings"])

def test_yardi_hostile_details(tmp_path):
    path = tmp_path / "rr.xlsx"
    builders.build_yardi_rent_roll(path)
    grid = excel_extractor.extract_grid(path, "xlsx")
    parsed = rent_roll_parser.parse_rows(grid["headers"], grid["rows"], "rr.xlsx", grid["sheet"])

    units = [r["unit"] for r in parsed["rows"]]
    assert "Total 1BR/1BA" not in units and "Total 2BR/2BA" not in units  # subtotals skipped
    assert len(parsed["rows"]) == 6  # 6 real units survive

    by_unit = {r["unit"]: r for r in parsed["rows"]}
    assert by_unit["A-103"]["status"] == "vacant"  # literal VACANT resident
    assert by_unit["B-203"]["status"] == "vacant"  # blank vacant row
    assert by_unit["A-101"]["status"] == "occupied"
    assert by_unit["A-101"]["leaseStart"] == "2024-05-01"  # US date parsed


def test_yardi_t12_hostile_details(tmp_path):
    path = tmp_path / "t12.xlsx"
    builders.build_yardi_t12(path)
    grid = excel_extractor.extract_grid(path, "xlsx")
    parsed = t12_parser.parse_t12(grid["headers"], grid["rows"], "t12.xlsx", grid["sheet"])
    aggregates = t12_parser.aggregate_categories(parsed["lineItems"])

    assert parsed["periodType"] == "T12"
    assert len(parsed["monthHeaders"]) == 12
    assert aggregates["income"]["vacancyLoss"] == -30_000  # "(2,500)" strings parsed negative
    assert aggregates["noi"] == 32_450 * 12
    unclassified_labels = {li["label"] for li in aggregates["unclassified"]}
    assert unclassified_labels == {"RUBS Income", "Pest Control"}


def test_om_pdf_merges_pages_and_drops_repeated_header(tmp_path):
    path = tmp_path / "om.pdf"
    builders.build_broker_om_pdf(path)
    pdf_data = pdf_extractor.extract_pdf(path)
    grid, warnings = _grid_from_pdf_tables(pdf_data["pages"])
    units = [row[0] for row in grid["rows"]]
    assert units == ["101", "102", "103", "104", "105"]
    assert any("merged 2 tables" in w for w in warnings)
