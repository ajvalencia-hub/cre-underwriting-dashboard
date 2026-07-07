"""L5: floating-rate debt + rate caps. Two layers, same structure as L4's
tests: pure unit tests on debt.py's hand-computable rate-resolution and
repricing math, and engine-level integration tests proving the floating
schedule is correctly threaded into the permanent loan (senior only —
construction-phase financing stays fixed always, see DECISIONS.md)."""

import json
from pathlib import Path

import pytest

from app.services.proforma import debt, engine

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def analytic() -> dict:
    return json.loads((FIXTURES / "analytic_acquisition.json").read_text())


@pytest.fixture
def analytic_dev() -> dict:
    return json.loads((FIXTURES / "analytic_development.json").read_text())


# ----------------------------------------------------------------------
# debt.resolve_floating_rate_schedule
# ----------------------------------------------------------------------

def test_step_interpolation_multi_point_curve():
    curve = [
        {"month": 0, "indexPct": 0.03},
        {"month": 12, "indexPct": 0.04},
        {"month": 24, "indexPct": 0.05},
    ]
    rates = debt.resolve_floating_rate_schedule(
        spread_bps=200, floor_pct=None, forward_curve=curve,
        current_index_pct=0.03, rate_cap=None, months=30,
    )
    # Step interpolation: the curve value at the largest month <= target wins.
    assert rates[0] == pytest.approx(0.05)     # month 1  -> 0.03 + 0.02
    assert rates[10] == pytest.approx(0.05)    # month 11 -> still 0.03 + 0.02
    assert rates[11] == pytest.approx(0.06)    # month 12 -> 0.04 + 0.02
    assert rates[22] == pytest.approx(0.06)    # month 23 -> still 0.04 + 0.02
    assert rates[23] == pytest.approx(0.07)    # month 24 -> 0.05 + 0.02
    assert rates[29] == pytest.approx(0.07)    # month 30 -> still 0.05 + 0.02


def test_no_curve_seeds_flat_schedule_from_current_index():
    rates = debt.resolve_floating_rate_schedule(
        spread_bps=150, floor_pct=None, forward_curve=[],
        current_index_pct=0.04, rate_cap=None, months=6,
    )
    assert rates == pytest.approx([0.055] * 6)


def test_floor_binds_below_index():
    rates = debt.resolve_floating_rate_schedule(
        spread_bps=150, floor_pct=0.04, forward_curve=[{"month": 0, "indexPct": 0.02}],
        current_index_pct=0.02, rate_cap=None, months=3,
    )
    assert rates == pytest.approx([0.055] * 3)  # max(0.02, 0.04) + 0.015


def test_floor_absent_never_clamps():
    rates = debt.resolve_floating_rate_schedule(
        spread_bps=150, floor_pct=None, forward_curve=[{"month": 0, "indexPct": 0.02}],
        current_index_pct=0.02, rate_cap=None, months=3,
    )
    assert rates == pytest.approx([0.035] * 3)  # 0.02 + 0.015, no floor


def test_cap_in_force_then_expires():
    rates = debt.resolve_floating_rate_schedule(
        spread_bps=100, floor_pct=None, forward_curve=[{"month": 0, "indexPct": 0.08}],
        current_index_pct=0.08, rate_cap={"strikePct": 0.05, "termMonths": 6}, months=8,
    )
    # Pre-cap all-in rate is 0.09 throughout; capped at 0.05+0.01=0.06 for
    # months 1-6, uncapped (0.09) for months 7-8 once the cap term expires.
    assert rates[:6] == pytest.approx([0.06] * 6)
    assert rates[6:] == pytest.approx([0.09] * 2)


# ----------------------------------------------------------------------
# debt.amortization_schedule (floating mode)
# ----------------------------------------------------------------------

def test_fixed_mode_unchanged_when_rate_is_a_float():
    # Existing callers (constant float) must be byte-identical to before.
    schedule = debt.amortization_schedule(100_000, 0.06, 30, 0, 12)
    assert schedule[0].payment == pytest.approx(debt.monthly_payment(100_000, 0.06, 30))


def test_floating_schedule_matches_fixed_when_rate_is_constant():
    fixed = debt.amortization_schedule(100_000, 0.06, 10, 0, 24)
    floating = debt.amortization_schedule(100_000, [0.06] * 24, 10, 0, 24)
    for f, g in zip(fixed, floating):
        assert f.payment == pytest.approx(g.payment)
        assert f.balance == pytest.approx(g.balance)


def test_floating_schedule_reprices_payment_each_amortizing_month():
    rates = [0.12, 0.24]
    schedule = debt.amortization_schedule(1200, rates, amort_years=1, io_months=0, months=2)
    # Month 1: payment prices off rate[0] over the full remaining (1yr) term.
    expected_payment_1 = debt.monthly_payment(1200, 0.12, 1)
    assert schedule[0].payment == pytest.approx(expected_payment_1)
    assert schedule[0].interest == pytest.approx(1200 * 0.12 / 12)
    # Month 2 REPRICES: payment recomputed off rate[1] against the month-1
    # ending balance and the remaining term (11/12 yr) — never the original
    # rate or the original principal (the whole point of a floating loan).
    expected_payment_2 = debt.monthly_payment(schedule[0].balance, 0.24, 11 / 12)
    assert schedule[1].payment == pytest.approx(expected_payment_2)
    assert schedule[1].interest == pytest.approx(schedule[0].balance * 0.24 / 12)


# ----------------------------------------------------------------------
# Engine integration
# ----------------------------------------------------------------------

def test_fixed_mode_reproduces_baseline(analytic):
    without = engine.compute(analytic)
    explicit_fixed = engine.compute({**analytic, "rateMode": "fixed"})
    assert without["outputs"]["leveredIrr"] == pytest.approx(explicit_fixed["outputs"]["leveredIrr"], abs=1e-12)
    assert "seniorRate" not in without["statement"]
    assert "stressedDscrBasis" not in without["outputs"]


def test_flat_floating_curve_matches_equivalent_fixed_rate(analytic):
    fixed = engine.compute(analytic)  # 6% fixed, IO, loanAmount=600,000
    floating = engine.compute({
        **analytic,
        "rateMode": "floating",
        "rateSpreadBps": 0,
        "rateCurrentIndexPct": 0.06,
    })
    assert floating["outputs"]["leveredIrr"] == pytest.approx(fixed["outputs"]["leveredIrr"], rel=1e-6)
    assert floating["outputs"]["equityMultiple"] == pytest.approx(fixed["outputs"]["equityMultiple"], rel=1e-6)


def test_floating_rate_threaded_into_debt_service(analytic):
    # Curve rate (4%) is BELOW the fixture's original 6% -> cheaper debt
    # service -> strictly better levered returns than the fixed baseline.
    result = engine.compute({
        **analytic,
        "rateMode": "floating",
        "rateSpreadBps": 0,
        "rateCurrentIndexPct": 0.04,
    })
    baseline = engine.compute(analytic)
    assert result["outputs"]["leveredIrr"] > baseline["outputs"]["leveredIrr"]
    assert result["statement"]["seniorRate"][1] == pytest.approx(0.04)


def test_capped_floating_stress_dscr_uses_cap_strike(analytic):
    inputs = {
        **analytic,
        "rateMode": "floating",
        "rateSpreadBps": 0,
        "rateCurrentIndexPct": 0.06,
        "rateCapStrikePct": 0.05,
        "rateCapTermMonths": 60,
    }
    result = engine.compute(inputs)
    assert result["outputs"]["stressedDscrBasis"] == "cap_strike"
    capped_constant = debt.annual_loan_constant(0.05, inputs["amortYears"])
    sizing_noi = 80_000  # flat-NOI fixture: stabilized == in-place == flat.
    expected = (sizing_noi * 0.90) / (inputs["loanAmount"] * capped_constant)
    assert result["outputs"]["stressedDscr"] == pytest.approx(expected, rel=1e-6)
    # The cap actually binds: 6% > cap all-in (5%) -> loan carries 5% the
    # whole (fully-IO) hold, cheaper than the fixture's original 6%.
    assert result["outputs"]["leveredIrr"] > engine.compute(analytic)["outputs"]["leveredIrr"]


def test_uncapped_floating_keeps_plus_200bps_basis(analytic):
    result = engine.compute({
        **analytic, "rateMode": "floating", "rateSpreadBps": 0, "rateCurrentIndexPct": 0.06,
    })
    assert "stressedDscrBasis" not in result["outputs"]
    assert "stressedDscr" in result["outputs"]


def test_curve_round_trips_deterministically(analytic):
    inputs = {
        **analytic,
        "rateMode": "floating",
        "rateSpreadBps": 150,
        "rateCurrentIndexPct": 0.03,
        "rateForwardCurve": [{"month": 0, "indexPct": 0.03}, {"month": 24, "indexPct": 0.05}],
    }
    first = engine.compute(json.loads(json.dumps(inputs)))
    second = engine.compute(json.loads(json.dumps(inputs)))
    assert first["outputs"]["leveredIrr"] == second["outputs"]["leveredIrr"]
    assert first["statement"]["seniorRate"] == second["statement"]["seniorRate"]


def test_development_construction_phase_stays_fixed_rate(analytic_dev):
    without = engine.compute(analytic_dev)
    with_floating_perm = engine.compute({
        **analytic_dev,
        "rateMode": "floating",
        "rateSpreadBps": 0,
        "rateCurrentIndexPct": 0.10,  # well above the fixture's 7% fixed rate
    })
    cap_interest_without = dict(without["sourcesAndUses"]["uses"])["Capitalized interest"]
    cap_interest_with = dict(with_floating_perm["sourcesAndUses"]["uses"])["Capitalized interest"]
    # Construction-phase financing is untouched by rateMode (v1 scoping
    # decision, DECISIONS.md) -> capitalized interest during the build is
    # byte-identical regardless of the PERM loan's floating rate.
    assert cap_interest_with == pytest.approx(cap_interest_without)
    # But the permanent takeout now carries the much higher floating rate.
    assert with_floating_perm["outputs"]["leveredIrr"] < without["outputs"]["leveredIrr"]


def test_development_floating_perm_matches_fixed_when_rate_equal(analytic_dev):
    # No refiRateSpreadPct set in the fixture (defaults 0) -> fixed perm_rate
    # == interestRate (7%). A flat floating curve at 7%/0 spread must match.
    without = engine.compute(analytic_dev)
    floating = engine.compute({
        **analytic_dev, "rateMode": "floating", "rateSpreadBps": 0, "rateCurrentIndexPct": 0.07,
    })
    assert floating["outputs"]["leveredIrr"] == pytest.approx(without["outputs"]["leveredIrr"], rel=1e-6)


def test_excel_export_refuses_floating_rate(analytic):
    from app.services.excel_model_export import unsupported_features

    active = {**analytic, "rateMode": "floating", "rateCurrentIndexPct": 0.05}
    assert any("floating-rate" in f.lower() for f in unsupported_features(active))
    assert not any("floating-rate" in f.lower() for f in unsupported_features(analytic))
