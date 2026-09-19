"""Quick Screen napkin vs the engine, on cases shared with the frontend
(roadmap #32). frontend/src/lib/quickScreenSharedCases.test.ts writes
fixtures/quick_screen_cases.json: each case's napkin results and the exact
"Send to Deal Inputs" payload. Here the engine computes that payload over
the schema defaults (what a new deal's form holds) and must land near the
napkin, so neither side can drift without a test failing.

The napkin models no loan or acquisition fees, so costs are compared
without them (the engine adds them from the form's defaults).
"""

import json
from pathlib import Path

import pytest

from app.services.proforma.engine import compute

_ROOT = Path(__file__).resolve().parents[1]
_CASES = json.loads((_ROOT / "tests" / "fixtures" / "quick_screen_cases.json").read_text())["cases"]
_SCHEMA = json.loads((_ROOT / "app" / "data" / "input_schema.json").read_text())
_DEFAULTS = {
    f["id"]: f["default"] for s in _SCHEMA["sections"] for f in s["fields"] if "default" in f
}
_FEES_THE_NAPKIN_OMITS = {"Loan fees", "Acquisition fee"}


def _engine(case: dict) -> dict:
    return compute({**_DEFAULTS, **case["dealInputs"]})


def _by_kind(kind: str) -> list:
    return [pytest.param(c, id=c["name"]) for c in _CASES if c["kind"] == kind]


@pytest.mark.parametrize("case", _by_kind("development") + _by_kind("acquisition"))
def test_total_cost_and_loan_match(case):
    result = _engine(case)
    su = result["sourcesAndUses"]
    cost = sum(amount for name, amount in su["uses"] if name not in _FEES_THE_NAPKIN_OMITS)
    # The napkin estimates capitalized interest with an average-draw factor
    # (QUICK_SCREEN_AVG_DRAW_FACTOR); the engine draws month by month.
    assert cost == pytest.approx(case["napkin"]["totalCost"], rel=0.01)
    loan = sum(amount for name, amount in su["sources"] if "loan" in name.lower())
    assert loan == pytest.approx(case["napkin"]["loanAmount"], rel=0.01, abs=1)


@pytest.mark.parametrize("case", _by_kind("acquisition"))
def test_acquisition_going_in_cap_matches(case):
    outputs = _engine(case)["outputs"]
    assert outputs["goingInCapRate"] == pytest.approx(case["napkin"]["goingInCapRate"], abs=1e-4)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Send to Deal Inputs leaves operating expenses out by design "
        "(mapQuickScreenToDealInputs), so Compute's NOI has no opex and its "
        "yield on cost reads about 2.4 points above the napkin's. Remove this "
        "marker once the payload carries the napkin's expenses."
    ),
)
@pytest.mark.parametrize("case", _by_kind("development"))
def test_development_yield_on_cost_matches(case):
    outputs = _engine(case)["outputs"]
    assert outputs["yieldOnCost"] == pytest.approx(case["napkin"]["yieldOnCost"], abs=0.0025)
