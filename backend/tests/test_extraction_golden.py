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


# ---------------------------------------------------------------------------
# Targeted assertions on the hostile details, independent of the golden blobs
# (so a bad regeneration can't silently bless a regression).
# ---------------------------------------------------------------------------


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
