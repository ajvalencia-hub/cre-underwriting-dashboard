"""Regression tests for FINDINGS.md M5: T-12 formats that report expenses as
negative numbers (accounting convention) must produce positive expense fields,
with the normalization visible as a note and a warning — never silent.
"""

from app.services import extraction_service
from app.services.extraction import t12_parser

_HEADERS = ["Line Item", "Total"]
_NEGATIVE_EXPENSE_ROWS = [
    ["Gross Potential Rent", 100000],
    ["Insurance", -12000],
    ["Real Estate Taxes", -50000],
    ["Management Fee", -4000],
]


def _parsed_items():
    parsed = t12_parser.parse_t12(_HEADERS, _NEGATIVE_EXPENSE_ROWS, "t12.xlsx", "Sheet1")
    return parsed["lineItems"]


def test_negative_expense_totals_are_flipped_and_reported():
    agg = t12_parser.aggregate_categories(_parsed_items())
    assert agg["expenses"]["insurance"] == 12000
    assert agg["expenses"]["realEstateTaxes"] == 50000
    assert agg["totalExpenses"] > 0
    assert set(agg["signNormalizedExpenses"]) == {"insurance", "realEstateTaxes", "managementFeePct"}


def test_positive_expenses_are_not_flagged():
    rows = [["Insurance", 12000], ["Real Estate Taxes", 50000]]
    parsed = t12_parser.parse_t12(_HEADERS, rows, "t12.xlsx", "Sheet1")
    agg = t12_parser.aggregate_categories(parsed["lineItems"])
    assert agg["signNormalizedExpenses"] == []


def test_review_fields_carry_positive_values_note_and_warning():
    merged = {
        "scalarExtractions": [],
        "rentRollRows": [],
        "t12LineItems": _parsed_items(),
        "unmatchedExtractions": [],
        "warnings": [],
    }
    fields = extraction_service._aggregate_to_fields(merged)

    assert fields["insurance"]["value"] == 12000
    assert "sign normalized" in fields["insurance"]["notes"]
    # Management fee: sign-normalized $ amount, then converted to % of GPR —
    # both facts must appear in the note.
    assert fields["managementFeePct"]["value"] == 0.04
    assert "Converted from $ amount" in fields["managementFeePct"]["notes"]
    assert "sign normalized" in fields["managementFeePct"]["notes"]
    assert any("sign-normalized" in w for w in merged["warnings"])
