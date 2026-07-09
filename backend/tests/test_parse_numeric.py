"""Regression tests for FINDINGS.md M4: percent-formatted strings must parse
at decimal-fraction scale ('12%' -> 0.12, not 12.0), without disturbing the
existing money/negative/None handling.
"""

import pytest

from app.services.extraction.excel_extractor import parse_numeric


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12%", 0.12),
        ("5.25%", 0.0525),
        ("(3.5%)", -0.035),  # parenthesized negative percent
        ("100%", 1.0),
    ],
)
def test_percent_strings_scale_to_decimal_fraction(raw, expected):
    assert parse_numeric(raw) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("$1,234.50", 1234.5),
        ("(1,234)", -1234.0),
        (12.3, 12.3),
        (7, 7.0),
    ],
)
def test_non_percent_parsing_unchanged(raw, expected):
    assert parse_numeric(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", [None, "", "-", "—", "N/A", "n/a", "%", "abc"])
def test_unparseable_values_return_none(raw):
    assert parse_numeric(raw) is None


@pytest.mark.parametrize("raw", ["JUN 25", "Profit & Loss 12 Month Recap", "Property: 123 Main St", "Q1 2026"])
def test_text_cells_with_embedded_digits_return_none(raw):
    """Regression (post-M audit): a text cell that happens to contain
    digits must never silently parse as a number. Before this guard,
    parse_numeric("JUN 25") stripped the letters and returned 25.0 instead
    of None — which corrupted the T-12 header-row auto-detector's
    text-vs-numeric cell scoring (it uses parse_numeric to tell a text
    header cell from a data cell), causing it to pick a decorative title/
    banner row over the real month-header row and lose every line item on
    a real, complete T-12 statement."""
    assert parse_numeric(raw) is None
