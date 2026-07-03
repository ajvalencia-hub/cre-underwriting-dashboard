"""Regression tests for FINDINGS.md M6: management fee $ must convert to %
using EGI (collections), not GPR. Preference order: the statement's own EGI
line, then EGI derived from GPR/vacancy/credit/other income, then GPR as a
last resort — with the basis named in the note in every case.
"""

import pytest

from app.services import extraction_service
from app.services.extraction import t12_parser

_HEADERS = ["Line Item", "Total"]


def _fields_for(rows):
    parsed = t12_parser.parse_t12(_HEADERS, rows, "t12.xlsx", "Sheet1")
    merged = {
        "scalarExtractions": [],
        "rentRollRows": [],
        "t12LineItems": parsed["lineItems"],
        "unmatchedExtractions": [],
        "warnings": [],
    }
    return extraction_service._aggregate_to_fields(merged)


def test_stated_egi_line_is_preferred():
    fields = _fields_for(
        [
            ["Gross Potential Rent", 100000],
            ["Vacancy Loss", -10000],
            ["Effective Gross Income", 90000],
            ["Management Fee", 4500],
        ]
    )
    assert fields["managementFeePct"]["value"] == pytest.approx(0.05)
    assert "EGI line" in fields["managementFeePct"]["notes"]


def test_egi_derived_from_income_lines_when_not_stated():
    fields = _fields_for(
        [
            ["Gross Potential Rent", 100000],
            ["Vacancy Loss", -15000],
            ["Other Income", 5000],
            ["Management Fee", 4500],
        ]
    )
    # basis = 100000 - 15000 + 5000 = 90000
    assert fields["managementFeePct"]["value"] == pytest.approx(0.05)
    assert "derived" in fields["managementFeePct"]["notes"]


def test_gpr_fallback_names_the_basis():
    fields = _fields_for(
        [
            ["Gross Potential Rent", 100000],
            ["Management Fee", 4000],
        ]
    )
    assert fields["managementFeePct"]["value"] == pytest.approx(0.04)
    assert "GPR" in fields["managementFeePct"]["notes"]


def test_no_income_basis_keeps_fee_as_unmatched_amount():
    fields = _fields_for([["Management Fee", 4000], ["Insurance", 9000]])
    assert "managementFeePct" not in fields
    assert fields["_unmatchedManagementFeeAmount"]["value"] == 4000
