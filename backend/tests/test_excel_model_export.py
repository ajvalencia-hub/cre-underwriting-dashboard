"""H11: native Excel model export — structural checks that don't need
LibreOffice (the value parity lives in tests/parity/run.py as
export_analytic_acquisition / export_amortizing_growth)."""

import json
from io import BytesIO
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import excel_model_export
from app.services.excel_model_export import (
    OUTPUT_CELLS,
    UnsupportedModelFeatures,
    build_model_workbook,
)
from app.services.proforma import engine

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def analytic() -> dict:
    return json.loads((FIXTURES / "analytic_acquisition.json").read_text())


def _workbook(inputs) -> openpyxl.Workbook:
    content, _ = build_model_workbook(inputs)
    return openpyxl.load_workbook(BytesIO(content))


def test_unsupported_features_refuse_with_the_full_list(analytic):
    hostile = {
        **analytic,
        "dealType": "development",
        "opexLineItems": [{"category": "taxes", "amount": 1, "basis": "annual_total"}],
        "waterfallTiers": [{"hurdlePct": 0.08}],
        "irrConvention": "xirr",
        "useReassessedTaxes": True,
        "commercialLeases": [{
            "tenant": "T", "sf": 1000, "startDate": "2026-01-01",
            "endDate": "2036-01-01", "baseRentPsfAnnual": 30,
        }],
    }
    with pytest.raises(UnsupportedModelFeatures) as excinfo:
        build_model_workbook(hostile)
    text = str(excinfo.value)
    for fragment in ("development", "lease", "line-item", "waterfall", "XIRR", "reassessed"):
        assert fragment in text, fragment


def test_workbook_is_formula_live_with_sized_loan(analytic):
    wb = _workbook(analytic)
    assert wb.calculation.fullCalcOnLoad
    out = wb["Outputs"]
    assert out[OUTPUT_CELLS["leveredIrr"]].value.startswith("=(1+IRR(")
    model = wb["Model"]
    assert model["B2"].value.startswith("=Inputs!$B$6/12")  # GPR is a formula
    assert model["I2"].value == "=F2-G2-H2"  # NOI identity
    # 60 hold months + 12 forward NOI months
    assert model.cell(row=73, column=9).value is not None
    assert model.cell(row=74, column=2).value is None

    # Loan cell carries the engine's sized amount as a VALUE.
    loan = engine.compute(analytic)["debt"]["loanAmount"]
    assert wb["Inputs"]["B12"].value == pytest.approx(loan)


def test_unit_mix_deals_collapse_income_with_a_warning(analytic):
    unit_mix_deal = {
        **analytic,
        "grossPotentialRent": 0,
        "unitMix": [{"unitType": "1BR", "unitCount": 50, "inPlaceRent": 1500}],
    }
    content, warnings = build_model_workbook(unit_mix_deal)
    assert any("collapsed to annual dollars" in w for w in warnings)
    wb = openpyxl.load_workbook(BytesIO(content))
    assert wb["Inputs"]["B6"].value == pytest.approx(50 * 1500 * 12)
    # ...and the warning also lands on the Notes sheet.
    notes = [c.value for c in wb["Notes"]["A"] if c.value]
    assert any("collapsed" in str(n) for n in notes)


def test_router_returns_workbook_or_422():
    client = TestClient(app)
    analytic = json.loads((FIXTURES / "analytic_acquisition.json").read_text())

    ok = client.post("/api/generate/model", json={"values": analytic})
    assert ok.status_code == 200
    assert ok.headers["content-type"].startswith("application/vnd.openxml")
    assert "X-Generation-Warnings" in ok.headers

    unsupported = client.post(
        "/api/generate/model",
        json={"values": {**analytic, "irrConvention": "xirr"}},
    )
    assert unsupported.status_code == 422
    assert "XIRR" in unsupported.json()["detail"]

    assert client.post("/api/generate/model", json={"values": {}}).status_code == 422


def test_output_cells_map_matches_the_sheet(analytic):
    wb = _workbook(analytic)
    out = wb["Outputs"]
    for output_id, cell in OUTPUT_CELLS.items():
        row = int(cell[1:])
        assert out.cell(row=row, column=6).value == output_id
        assert str(out[cell].value).startswith("=")


def test_export_module_importable_from_run():
    # run.py imports this lazily; keep the seam honest.
    from tests.parity.export_case import AMORTIZING_GROWTH_INPUTS, run_export_parity  # noqa: F401

    assert excel_model_export.unsupported_features(AMORTIZING_GROWTH_INPUTS) == []
