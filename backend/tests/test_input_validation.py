"""Engine inputs are type- and range-checked against the schema (engine
audit fix). A vacancy imported as the text "0.1" used to read as 0 and move
levered IRR from 11.57% to 15.39% without a word."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import compute_cache
from app.services.proforma import engine

_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def analytic():
    data = json.loads((_FIXTURES / "analytic_acquisition.json").read_text())
    data.pop("_comment", None)
    return data


def test_numeric_text_is_read_as_the_number_with_a_warning(analytic):
    as_text = engine.compute(dict(analytic, vacancyPct="0.1", purchasePrice="$1,000,000"))
    assert as_text["outputs"]["leveredIrr"] == pytest.approx(engine.compute(analytic)["outputs"]["leveredIrr"])
    assert "Vacancy" in as_text["warnings"][0] and "read as 0.1" in as_text["warnings"][0]
    assert any("read as 1e+06" in w for w in as_text["warnings"])


def test_non_numeric_value_stops_the_compute_naming_the_field(analytic):
    with pytest.raises(engine.InsufficientInputsError) as err:
        engine.compute(dict(analytic, vacancyPct="ten percent"))
    assert err.value.missing == ["vacancyPct (not a number: 'ten percent')"]


def test_non_numeric_table_cell_is_named_by_row(analytic):
    deal = dict(analytic, unitMix=[{"unitType": "1BR", "unitCount": "lots", "inPlaceRent": 1000}])
    with pytest.raises(engine.InsufficientInputsError) as err:
        engine.compute(deal)
    assert err.value.missing == ["unitMix (row 1 unitCount: not a number: 'lots')"]


def test_out_of_range_computes_as_entered_with_a_warning(analytic):
    result = engine.compute(dict(analytic, vacancyPct=1.5))
    assert any(w.startswith("Vacancy") and "150%" in w and "computed as entered" in w for w in result["warnings"])


def test_zero_switches_a_sizing_constraint_off_without_a_warning(analytic):
    result = engine.compute(dict(analytic, dscrConstraint=0))
    assert not any("DSCR Sizing" in w for w in result["warnings"])


def test_api_returns_422_for_a_non_numeric_input(analytic):
    compute_cache.clear()
    response = TestClient(app).post("/api/compute", json={"values": dict(analytic, interestRate="six")})
    assert response.status_code == 422
    assert "interestRate" in response.text
