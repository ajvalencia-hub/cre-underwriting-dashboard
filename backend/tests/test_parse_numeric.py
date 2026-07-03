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
