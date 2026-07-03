"""Regression tests for FINDINGS.md M7: a clean annual-only operating
statement (Total column, no month columns) could never pass the deterministic
confidence gate — (0 months + 1)/12 = 0.08 < 0.4 — and always fell to the
LLM even when every row parsed perfectly. Confidence now also scores parse
quality, while badly-classifying statements still fall through to the LLM.
"""

from app.services.extraction import t12_parser

# The gate used by extraction_service._extract_t12.
_GATE = 0.4

_ANNUAL_HEADERS = ["Line Item", "Annual Total"]


def test_clean_annual_only_statement_passes_the_gate():
    rows = [
        ["Gross Potential Rent", 500000],
        ["Vacancy Loss", -25000],
        ["Other Income", 12000],
        ["Real Estate Taxes", 60000],
        ["Insurance", 18000],
        ["Utilities", 30000],
        ["Repairs and Maintenance", 22000],
        ["Management Fee", 20000],
        ["Total Expenses", 150000],
        ["Net Operating Income", 337000],
    ]
    parsed = t12_parser.parse_t12(_ANNUAL_HEADERS, rows, "t12.xlsx", "Sheet1")
    assert parsed["periodType"] == "annual"
    assert parsed["confidence"] >= _GATE
    assert len(parsed["lineItems"]) == len(rows)


def test_annual_statement_with_unrecognizable_labels_still_falls_to_llm():
    rows = [
        ["Alpha Charge", 5000],
        ["Beta Assessment", 3000],
        ["Gamma Levy", 7000],
        ["Delta Cost", 2000],
    ]
    parsed = t12_parser.parse_t12(_ANNUAL_HEADERS, rows, "t12.xlsx", "Sheet1")
    assert parsed["confidence"] < _GATE


def test_twelve_month_statement_confidence_unchanged():
    headers = ["Line Item"] + ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"] + ["Total"]
    rows = [["Weird Uncategorizable Line"] + [100] * 12 + [1200]]
    parsed = t12_parser.parse_t12(headers, rows, "t12.xlsx", "Sheet1")
    # Structure alone keeps a full monthly grid at high confidence even when
    # the labels don't classify.
    assert parsed["confidence"] == 1.0
