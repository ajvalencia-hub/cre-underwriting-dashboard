"""Regression test (post-M audit): _guess_header_row must find the real
month-header row even when a merged decorative banner row sits directly
above it and several single-cell metadata rows sit above that — a shape a
real property-management T-12 export used. Before the parse_numeric letter
guard (see test_parse_numeric.py), month headers like "Jan 2026" silently
parsed as numbers (the letters got stripped, leaving "2026"), so the
header-row scorer couldn't tell those cells were text — it picked a
decorative banner row instead, found zero month columns, and every line
item on a complete, real T-12 statement was silently dropped (0 of ~100
rows extracted, with no warning surfaced to the user)."""

from app.services.extraction import excel_extractor, t12_parser
from tests.extraction_corpus import builders


def test_header_row_found_past_a_merged_banner_row(tmp_path):
    path = tmp_path / "t12_banner.xlsx"
    builders.build_property_management_t12_with_banner_row(path)

    grid = excel_extractor.extract_grid(path, "xlsx")
    assert grid["headers"][1:13] == [
        "Jan 2026", "Feb 2026", "Mar 2026", "Apr 2026", "May 2026", "Jun 2026",
        "Jul 2026", "Aug 2026", "Sep 2026", "Oct 2026", "Nov 2026", "Dec 2026",
    ]

    parsed = t12_parser.parse_t12(grid["headers"], grid["rows"], "t12_banner.xlsx", grid["sheet"])
    assert parsed["periodType"] == "T12"
    assert parsed["confidence"] == 1.0

    labels = {li["label"]: li for li in parsed["lineItems"]}
    assert labels["411010 Rental Income"]["amount"] == 600_000
    assert labels["411010 Rental Income"]["category"] is None  # account-code prefix, unclassified by design
    assert labels["501510 Exp:Prop-Taxes-Paid"]["category"] == "realEstateTaxes"
    assert labels["502832 Electricity - Common Area"]["category"] == "utilities"
