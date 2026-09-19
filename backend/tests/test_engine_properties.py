"""Property-based engine tests (roadmap #32).

Hypothesis perturbs the two analytic fixtures within the input schema's own
ranges and checks what must hold for every deal the form accepts:
- compute returns a result or a typed InsufficientInputsError, nothing else;
- no headline metric is NaN or infinite;
- sources equal uses;
- a higher exit cap never moves the terminal value away from zero, and a
  higher purchase price never moves the going-in cap rate away from zero.
"""

import json
import math
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.services.proforma.engine import InsufficientInputsError, compute

_FIXTURES = Path(__file__).parent / "fixtures"
_SCHEMA = json.loads(
    (Path(__file__).resolve().parents[1] / "app" / "data" / "input_schema.json").read_text()
)
_FIELDS = [
    f for section in _SCHEMA["sections"] for f in section["fields"] if not f.get("templateOnly")
]
_NUMERIC = [f for f in _FIELDS if f["type"] in {"currency", "percent", "number", "multiple", "years"}]
_SELECTS = [f for f in _FIELDS if f["type"] == "select" and f.get("options") and f["id"] != "dealType"]

PROFILE = settings(
    max_examples=150,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
    derandomize=True,  # the same examples every run, so CI can't flake
)


def _fixture(name: str) -> dict:
    data = json.loads((_FIXTURES / name).read_text())
    data.pop("_comment", None)
    return data


def _value_strategy(field: dict, base) -> st.SearchStrategy:
    low = field.get("min", 0)
    high = field.get("max")
    if field["type"] == "percent":
        # To a millionth (0.0001 points), for the same reason as cents below.
        top = high if high is not None else 1.0
        return st.integers(math.ceil(low * 1e6), math.floor(top * 1e6)).map(lambda u: u / 1e6)
    if field["type"] == "currency":
        anchor = base if isinstance(base, (int, float)) and base > 0 else 1_000_000
        # Whole cents: a loan of 1e-311 dollars isn't an input anyone types.
        top = high if high is not None else anchor * 4
        return st.integers(math.ceil(low * 100), math.floor(top * 100)).map(lambda c: c / 100)
    # Counts of months and years: whole numbers, capped so a draw can't ask
    # for a thousand-year hold.
    anchor = base if isinstance(base, (int, float)) and base > 0 else 12
    top = high if high is not None else max(anchor * 3, 12)
    return st.integers(math.ceil(low), math.floor(top))


@st.composite
def perturbed_deal(draw, fixture: str) -> dict:
    deal = _fixture(fixture)
    numeric = draw(st.lists(st.sampled_from(_NUMERIC), max_size=8, unique_by=lambda f: f["id"]))
    for field in numeric:
        deal[field["id"]] = draw(_value_strategy(field, deal.get(field["id"])))
    selects = draw(st.lists(st.sampled_from(_SELECTS), max_size=3, unique_by=lambda f: f["id"]))
    for field in selects:
        deal[field["id"]] = draw(st.sampled_from(field["options"]))
    return deal


def _run(deal: dict) -> dict | None:
    try:
        return compute(deal)
    except InsufficientInputsError:
        return None  # a typed 4xx the UI shows next to the field


def _check_invariants(result: dict) -> None:
    for key, value in result["outputs"].items():
        if isinstance(value, float):
            assert math.isfinite(value), f"{key} = {value}"
    su = result["sourcesAndUses"]
    uses = sum(amount for _, amount in su["uses"])
    sources = sum(amount for _, amount in su["sources"])
    assert sources == pytest.approx(uses, rel=1e-9, abs=0.01)


@pytest.mark.parametrize("fixture", ["analytic_acquisition.json", "analytic_development.json"])
def test_perturbed_deals_compute_cleanly(fixture):
    @PROFILE
    @given(perturbed_deal(fixture))
    def check(deal):
        result = _run(deal)
        if result is not None:
            _check_invariants(result)

    check()


@PROFILE
@given(
    deal=perturbed_deal("analytic_acquisition.json"),
    low=st.floats(0.03, 0.10),
    bump=st.floats(0.0025, 0.03),
)
def test_higher_exit_cap_never_raises_terminal_value(deal, low, bump):
    lower = _run(dict(deal, exitCapRatePct=low))
    higher = _run(dict(deal, exitCapRatePct=low + bump))
    if lower is None or higher is None:
        return
    tv_low = lower["outputs"].get("terminalValue")
    tv_high = higher["outputs"].get("terminalValue")
    if tv_low is None or tv_high is None:
        return
    # With negative exit NOI the terminal value is negative and a higher cap
    # moves it towards zero, so compare magnitudes.
    assert abs(tv_high) <= abs(tv_low) + 1e-6


@PROFILE
@given(
    deal=perturbed_deal("analytic_acquisition.json"),
    factor=st.floats(1.01, 2.0),
)
def test_higher_price_never_raises_going_in_cap(deal, factor):
    price = deal.get("purchasePrice") or 0
    if price <= 0:
        return
    base = _run(deal)
    dearer = _run(dict(deal, purchasePrice=price * factor))
    if base is None or dearer is None:
        return
    cap_base = base["outputs"].get("goingInCapRate")
    cap_dearer = dearer["outputs"].get("goingInCapRate")
    if cap_base is None or cap_dearer is None:
        return
    # Paying more pulls the cap rate towards zero; with negative NOI that
    # means it rises, so compare magnitudes.
    assert abs(cap_dearer) <= abs(cap_base) + 1e-12
