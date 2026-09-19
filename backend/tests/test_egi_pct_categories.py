"""pct_of_egi opex lines report under their OWN category: only
management_fee rows (plus legacy managementFeePct) are the statement's
managementFee; an `other` row at % of EGI lands under otherOpex. The split
is reporting-only — opex, NOI, and every output are unchanged."""

import copy
import json
from pathlib import Path

import openpyxl
import pytest

from app.services.excel_model_export import build_model_workbook
from app.services.proforma import engine

TESTS = Path(__file__).parent


def _line(category, amount, basis="annual_total"):
    return {"category": category, "amount": amount, "basis": basis, "recoverable": "no"}


@pytest.fixture
def analytic() -> dict:
    return json.loads((TESTS / "fixtures" / "analytic_acquisition.json").read_text())


def _with_lines(inputs: dict, lines: list[dict]) -> dict:
    return {**copy.deepcopy(inputs), "opexLineItems": lines}


def _assert_same_numbers(a: dict, b: dict):
    for key, value in a["outputs"].items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            assert b["outputs"][key] == pytest.approx(value, rel=1e-9, abs=1e-9), key
    for key in ("noi", "egi", "opexTotal"):
        assert b["statement"][key] == pytest.approx(a["statement"][key], rel=1e-9, abs=1e-9)


def _check_split(result: dict, other_pct: float, mgmt_pct: float):
    stmt = result["statement"]
    egi = stmt["egi"]
    other = stmt["fixedOpexByCategory"]["otherOpex"]
    assert other == pytest.approx([e * other_pct for e in egi], rel=1e-9, abs=1e-9)
    assert stmt["managementFee"] == pytest.approx(
        [e * mgmt_pct for e in egi], rel=1e-9, abs=1e-9
    )
    # category rows + mgmt fee still sum to total opex
    for m in range(len(egi)):
        total = sum(v[m] for v in stmt["fixedOpexByCategory"].values()) + stmt["managementFee"][m]
        assert total == pytest.approx(stmt["opexTotal"][m], rel=1e-9, abs=1e-6)


def test_other_pct_row_lands_under_other_opex_not_management_fee(analytic):
    lines = [_line("taxes", 20_000), _line("other", 0.02, "pct_of_egi")]
    result = engine.compute(_with_lines(analytic, lines))
    stmt = result["statement"]
    assert "otherOpex" in stmt["fixedOpexByCategory"]
    assert any(v > 0 for v in stmt["fixedOpexByCategory"]["otherOpex"])
    assert all(v == 0 for v in stmt["managementFee"])
    _check_split(result, other_pct=0.02, mgmt_pct=0.0)

    # Numbers match the same deal with the row modeled as a management fee.
    as_mgmt = engine.compute(
        _with_lines(analytic, [_line("taxes", 20_000), _line("management_fee", 0.02, "pct_of_egi")])
    )
    _assert_same_numbers(as_mgmt, result)
    assert "otherOpex" not in as_mgmt["statement"]["fixedOpexByCategory"]


def test_mixed_categories_split_and_merge_with_dollar_lines(analytic):
    lines = [
        _line("other", 12_000),                       # dollar otherOpex line
        _line("other", 0.015, "pct_of_egi"),          # merges into otherOpex
        _line("management_fee", 0.03, "pct_of_egi"),
    ]
    result = engine.compute(_with_lines(analytic, lines))
    stmt = result["statement"]
    egi = stmt["egi"]
    ops_months = [m for m in range(1, len(egi)) if egi[m] > 0]
    m = ops_months[0]
    assert stmt["fixedOpexByCategory"]["otherOpex"][m] == pytest.approx(
        12_000 / 12 + egi[m] * 0.015
    )
    assert stmt["managementFee"][m] == pytest.approx(egi[m] * 0.03)


@pytest.mark.parametrize("fixture", [
    TESTS / "parity" / "corpus" / "commercial_nnn" / "inputs.json",      # lease path
    TESTS / "regression" / "fixtures" / "mixed_use.json",               # mixed-use
    TESTS / "fixtures" / "analytic_development.json",                   # construction
])
def test_other_pct_split_across_builders(fixture):
    base = json.loads(fixture.read_text())
    dollars = [r for r in (base.get("opexLineItems") or []) if r.get("basis") != "pct_of_egi"]
    dollars = dollars or [_line("insurance", 30_000)]
    split = engine.compute(_with_lines(
        base, dollars + [_line("other", 0.02, "pct_of_egi"), _line("management_fee", 0.03, "pct_of_egi")]
    ))
    as_mgmt = engine.compute(_with_lines(base, dollars + [_line("management_fee", 0.05, "pct_of_egi")]))
    _assert_same_numbers(as_mgmt, split)
    assert split["statement"]["breakEvens"] == as_mgmt["statement"]["breakEvens"]
    _check_split(split, other_pct=0.02, mgmt_pct=0.03)


def test_excel_export_keeps_other_pct_out_of_the_fee_cell(analytic):
    inputs = _with_lines(analytic, [
        _line("taxes", 20_000),
        _line("other", 0.02, "pct_of_egi"),
        _line("management_fee", 0.03, "pct_of_egi"),
    ])
    content, _ = build_model_workbook(inputs)
    from io import BytesIO
    ws = openpyxl.load_workbook(BytesIO(content))["Inputs"]
    cells = {str(r[0].value): r[1].value for r in ws.iter_rows(min_col=1, max_col=2) if r[0].value}
    assert cells["Mgmt fee % of EGI"] == pytest.approx(0.03)
    assert cells["Other opex (detail) % of EGI"] == pytest.approx(0.02)
