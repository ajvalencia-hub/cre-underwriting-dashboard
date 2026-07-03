"""F3: permanent-loan sizing (one case per governing constraint), the IO vs
amortizing DSCR basis, the stress matrix, and engine integration
(sizing-basis resolution, takeout paydown warning, stressed-DSCR output).
"""

import json
from pathlib import Path

import pytest

from app.services.proforma import engine
from app.services.proforma.debt import (
    annual_loan_constant,
    size_permanent_loan,
    stress_matrix,
)

FIXTURES = Path(__file__).parent / "fixtures"

# Shared hand numbers: NOI 1.0M, value 12.5M (8% cap), 6%/30yr amortizing
# constant = 12 x PMT(1, 6%, 30) = 0.0719461.
_CONSTANT_6_30 = annual_loan_constant(0.06, 30)


def test_ltv_governs():
    sizing = size_permanent_loan(1_000_000, 12_500_000, 0.65, 1.25, 0.08, 0.06, 30)
    assert sizing.governing_constraint == "ltv"
    assert sizing.amount == pytest.approx(8_125_000)
    # The DSCR candidate is computed but does not govern here.
    assert sizing.candidates["dscr"] == pytest.approx(1_000_000 / 1.25 / _CONSTANT_6_30, rel=1e-9)


def test_dscr_governs():
    sizing = size_permanent_loan(1_000_000, 12_500_000, 0.80, 1.25, 0.08, 0.08, 30)
    assert sizing.governing_constraint == "dscr"
    constant = annual_loan_constant(0.08, 30)
    assert sizing.amount == pytest.approx(1_000_000 / 1.25 / constant, rel=1e-9)
    assert sizing.amount < 10_000_000  # below the LTV candidate


def test_debt_yield_governs():
    sizing = size_permanent_loan(1_000_000, 12_500_000, 0.80, 1.25, 0.12, 0.08, 30)
    assert sizing.governing_constraint == "debtYield"
    assert sizing.amount == pytest.approx(1_000_000 / 0.12)


def test_fully_io_loan_sizes_on_interest_only_constant():
    # amort_years = 0 -> constant = rate, so the same DSCR supports more debt.
    assert annual_loan_constant(0.06, 0) == pytest.approx(0.06)
    io_sizing = size_permanent_loan(1_000_000, 99_000_000, 0.99, 1.25, 0.0001, 0.06, 0)
    amort_sizing = size_permanent_loan(1_000_000, 99_000_000, 0.99, 1.25, 0.0001, 0.06, 30)
    assert io_sizing.governing_constraint == "dscr"
    assert io_sizing.amount == pytest.approx(1_000_000 / 1.25 / 0.06)
    assert io_sizing.amount > amort_sizing.amount


def test_no_usable_constraints():
    sizing = size_permanent_loan(0, 0, 0, 0, 0, 0.06, 30)
    assert sizing.amount == 0.0
    assert sizing.governing_constraint == "none"


def test_stress_matrix_recomputes_dscr_and_refi_proceeds():
    cells = stress_matrix(
        sizing_noi=1_000_000, value=12_500_000, loan_amount=8_125_000,
        max_ltv=0.65, min_dscr=1.25, min_debt_yield=0.08,
        annual_rate=0.06, amort_years=30,
    )
    assert len(cells) == 9
    base = next(c for c in cells if c["rateBumpBps"] == 0 and c["noiHaircutPct"] == 0)
    assert base["dscr"] == pytest.approx(1_000_000 / (8_125_000 * _CONSTANT_6_30), rel=1e-9)
    assert base["refiShortfall"] == 0.0

    worst = next(c for c in cells if c["rateBumpBps"] == 200 and c["noiHaircutPct"] == 0.10)
    stressed_constant = annual_loan_constant(0.08, 30)
    assert worst["dscr"] == pytest.approx(900_000 / (8_125_000 * stressed_constant), rel=1e-9)
    # Refi at stressed NOI/value: LTV governs at 0.65 x 11.25M = 7.3125M.
    assert worst["refiProceeds"] == pytest.approx(0.65 * 12_500_000 * 0.9)
    assert worst["refiShortfall"] == pytest.approx(8_125_000 - 7_312_500)


# ------------------------------------------------------------- engine level

@pytest.fixture
def analytic() -> dict:
    return json.loads((FIXTURES / "analytic_acquisition.json").read_text())


def test_engine_reports_governing_constraint_and_stressed_dscr(analytic):
    result = engine.compute(analytic)
    out = result["outputs"]
    assert out["governingConstraint"] == "Manual (loan amount input)"
    stressed_constant = annual_loan_constant(0.08, 30)
    assert out["stressedDscr"] == pytest.approx(72_000 / (600_000 * stressed_constant), abs=1e-6)
    assert result["debt"]["stress"][0]["rateBumpBps"] == 0
    assert result["debt"]["loanAmount"] == pytest.approx(600_000)


def test_engine_sizes_loan_when_no_explicit_amount(analytic):
    inputs = {**analytic, "loanAmount": 0, "ltvOrLtc": 0.99, "sizingNoiBasis": "stabilized"}
    result = engine.compute(inputs)
    # ltv candidate 990k, dy candidate 1.0M, dscr candidate 889.6k -> dscr governs.
    assert result["outputs"]["governingConstraint"] == "DSCR"
    assert result["debt"]["loanAmount"] == pytest.approx(80_000 / 1.25 / _CONSTANT_6_30, rel=1e-6)


def test_sizing_noi_basis_in_place_uses_the_input(analytic):
    inputs = {
        **analytic,
        "loanAmount": 0,
        "ltvOrLtc": 0.99,
        "sizingNoiBasis": "in_place",
        "inPlaceNoi": 60_000,
    }
    result = engine.compute(inputs)
    assert result["debt"]["sizingNoi"] == pytest.approx(60_000)
    assert result["debt"]["loanAmount"] == pytest.approx(60_000 / 1.25 / _CONSTANT_6_30, rel=1e-6)


def test_oversized_manual_loan_warns(analytic):
    inputs = {**analytic, "loanAmount": 5_000_000}
    result = engine.compute(inputs)
    assert any("exceeds the constraint-sized proceeds" in w for w in result["warnings"])


def test_development_takeout_paydown_warns(analytic):
    inputs = {
        **analytic,
        "dealType": "development",
        "landCost": 1_000_000,
        "hardCosts": 8_000_000,
        "softCosts": 1_000_000,
        "contingencyPct": 0.05,
        "developerFeePct": 0.04,
        "constructionMonths": 12,
        "leaseUpMonths": 6,
        "grossPotentialRent": 1_000_000,
        "exitCapRatePct": 0.10,  # low value -> LTV sizes below construction debt
        "ltvOrLtc": 0.85,
        "loanAmount": 0,
    }
    result = engine.compute(inputs)
    assert any("equity paydown is required at takeout" in w for w in result["warnings"])
    assert result["outputs"]["governingConstraint"] == "LTV"
