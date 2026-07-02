"""Regression tests for FINDINGS.md C3: a T-12 row whose Total cell is blank or
unparseable must fall back to summing its month columns, not be dropped.
"""

from app.services.extraction.t12_parser import parse_t12

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
HEADERS = ["Line Item", *MONTHS, "Total"]


def test_blank_total_falls_back_to_month_sum():
    rows = [
        ["Gross Potential Rent", *[100] * 12, 1200],
        ["Insurance", *[10] * 12, None],  # blank total — pre-fix this row vanished
        ["Utilities", *[5] * 12, "-"],  # dash total — same failure
    ]
    parsed = parse_t12(HEADERS, rows, "t12.xlsx", "Sheet1")
    by_label = {li["label"]: li["amount"] for li in parsed["lineItems"]}

    assert by_label["Gross Potential Rent"] == 1200  # total column still preferred
    assert by_label["Insurance"] == 120  # summed from months
    assert by_label["Utilities"] == 60


def test_t6_fallback_applies_annualize_factor():
    t6_headers = ["Line Item", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Total"]
    rows = [["Insurance", 10, 10, 10, 10, 10, 10, None]]
    parsed = parse_t12(t6_headers, rows, "t12.xlsx", "Sheet1")

    assert parsed["periodType"] == "T6"
    assert parsed["lineItems"][0]["amount"] == 120  # 60 × factor 2


def test_row_with_no_data_anywhere_is_still_skipped():
    rows = [["Section Header", *[None] * 12, None]]
    parsed = parse_t12(HEADERS, rows, "t12.xlsx", "Sheet1")
    assert parsed["lineItems"] == []
