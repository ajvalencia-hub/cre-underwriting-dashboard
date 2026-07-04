"""H3: expense-line detail — equivalence with the single-opex path, each
basis type, recoverable flags feeding NNN recoveries, and insurance stress."""

import json
from pathlib import Path

import pytest

from app.services.proforma import engine, operations
from app.services.proforma.timeline import Timeline

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def analytic() -> dict:
    return json.loads((FIXTURES / "analytic_acquisition.json").read_text())


def _line(category, amount, basis="annual_total", growth=None, recoverable="no"):
    row = {"category": category, "amount": amount, "basis": basis, "recoverable": recoverable}
    if growth is not None:
        row["growthPct"] = growth
    return row


def test_detail_reproduces_the_equivalent_single_opex_deal(analytic):
    """The flat expense fields, re-expressed as detail lines with the same
    growth, must produce identical outputs. (The fixture's insurance/mgmt are
    zero, so both sides get non-zero overrides to make the test meaningful.)"""
    base_inputs = {**analytic, "insurance": 6_000, "managementFeePct": 0.03}
    detail = {
        **base_inputs,
        "opexLineItems": [
            _line("taxes", base_inputs["realEstateTaxes"]),
            _line("insurance", base_inputs["insurance"]),
            _line("management_fee", base_inputs["managementFeePct"], basis="pct_of_egi"),
        ],
        # detail mode ignores the flat fields — zero them to prove it
        "realEstateTaxes": 0, "insurance": 0, "managementFeePct": 0,
    }
    base = engine.compute(base_inputs)
    detailed = engine.compute(detail)
    for key, value in base["outputs"].items():
        if isinstance(value, float):
            assert detailed["outputs"][key] == pytest.approx(value, rel=1e-9), key
    # ...and the statement breaks out the categories
    assert "realEstateTaxes" in detailed["statement"]["fixedOpexByCategory"]
    assert "insurance" in detailed["statement"]["fixedOpexByCategory"]


def test_basis_types():
    inputs = {
        "unitMix": [{"unitType": "1BR", "unitCount": 20, "inPlaceRent": 1500}],
        "commercialLeases": [], "vacancyPct": 0, "creditLossPct": 0,
        "rentGrowthMode": "flat", "expenseGrowthMode": "flat",
        "opexLineItems": [
            _line("taxes", 24_000),                       # annual_total
            _line("utilities", 300, basis="per_unit"),    # 300 x 20 = 6,000/yr
            _line("management_fee", 0.04, basis="pct_of_egi"),
        ],
    }
    ops = operations.build_noi_vector(inputs, Timeline(12, 0, 0, 1))
    by_cat = ops["fixedOpexByCategory"]
    assert by_cat["realEstateTaxes"][0] == pytest.approx(2_000)
    assert by_cat["utilities"][0] == pytest.approx(500)
    # EGI = 20 x 1500 = 30,000/mo; mgmt = 4% x EGI
    assert ops["managementFee"][0] == pytest.approx(30_000 * 0.04)

    psf_inputs = {
        **inputs,
        "unitMix": [], "rentableSf": 10_000, "rentPsf": 24,
        "opexLineItems": [_line("insurance", 1.2, basis="psf")],  # 12,000/yr
    }
    psf_ops = operations.build_noi_vector(psf_inputs, Timeline(12, 0, 0, 1))
    assert psf_ops["fixedOpexByCategory"]["insurance"][0] == pytest.approx(1_000)


def test_per_unit_without_units_warns_and_falls_back():
    inputs = {
        "grossPotentialRent": 120_000, "vacancyPct": 0, "creditLossPct": 0,
        "rentGrowthMode": "flat", "expenseGrowthMode": "flat",
        "opexLineItems": [_line("payroll", 12_000, basis="per_unit")],
    }
    ops = operations.build_noi_vector(inputs, Timeline(12, 0, 0, 1))
    assert ops["fixedOpexByCategory"]["payroll"][0] == pytest.approx(1_000)  # annual fallback
    assert any("per_unit" in w for w in ops["warnings"])


def test_recoverable_flags_feed_nnn_recoveries():
    """Only recoverable-flagged lines flow to a single NNN tenant: taxes
    (recoverable, $36k) recovered in full; insurance ($12k, not flagged)
    excluded -> recoveries = $3,000/mo."""
    inputs = {
        "commercialLeases": [{
            "tenant": "T", "suiteId": "1", "sf": 5_000,
            "startDate": "2026-01-01", "endDate": "2033-12-31",
            "baseRentPsfAnnual": 20, "escalationType": "none",
            "recoveryType": "NNN", "freeRentMonths": 0,
        }],
        "creditLossPct": 0, "rentGrowthMode": "flat", "expenseGrowthMode": "flat",
        "opexLineItems": [
            _line("taxes", 36_000, recoverable="yes"),
            _line("insurance", 12_000, recoverable="no"),
        ],
    }
    ops = operations.build_noi_vector(inputs, Timeline(12, 0, 0, 1))
    assert ops["recoveries"][0] == pytest.approx(3_000)


def test_per_line_growth_overrides_deal_growth():
    inputs = {
        "grossPotentialRent": 120_000, "vacancyPct": 0, "creditLossPct": 0,
        "rentGrowthMode": "flat", "expenseGrowthMode": "per_year", "expenseGrowthPct": 0.02,
        "opexLineItems": [
            _line("taxes", 12_000, growth=0.10),   # explicit 10%
            _line("insurance", 12_000),            # falls back to 2%
        ],
    }
    ops = operations.build_noi_vector(inputs, Timeline(24, 0, 0, 1))
    assert ops["fixedOpexByCategory"]["realEstateTaxes"][12] == pytest.approx(1_000 * 1.10)
    assert ops["fixedOpexByCategory"]["insurance"][12] == pytest.approx(1_000 * 1.02)


def test_insurance_stress_rows(analytic):
    detail = {
        **analytic,
        "opexLineItems": [
            _line("taxes", analytic["realEstateTaxes"]),
            _line("insurance", 6_000),
            _line("management_fee", 0.03, basis="pct_of_egi"),
        ],
        "realEstateTaxes": 0, "insurance": 0, "managementFeePct": 0,
    }
    result = engine.compute(detail)
    stress = result["debt"]["insuranceStress"]
    assert [row["bumpPct"] for row in stress] == [0.25, 0.50]
    base_dscr = result["outputs"]["minDscr"]
    assert stress[0]["minDscr"] < base_dscr
    assert stress[1]["minDscr"] < stress[0]["minDscr"]
    # CF delta scales with the bump: the +50% delta is twice the +25% delta
    # (management fee is EGI-based, so insurance flows through linearly).
    assert stress[1]["leveredCfDeltaAnnual"] == pytest.approx(
        2 * stress[0]["leveredCfDeltaAnnual"], rel=1e-6
    )
    assert stress[0]["leveredCfDeltaAnnual"] < 0

    # No detail mode -> no categorical stress block; panel degrades.
    base = engine.compute(analytic)
    assert "insuranceStress" not in (base["debt"] or {})
