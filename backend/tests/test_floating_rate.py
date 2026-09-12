"""J5: floating-rate senior debt + rate cap.

Base fixture = the analytic acquisition: explicit 600,000 loan, IO for the
whole 60-month hold, so month-m debt service is exactly
600,000 x rate(m) / 12 — every case below is hand-derivable.

Conventions under test (DECISIONS.md):
- rate(m) = max(index(m), floor) + spread, capped at strike + spread while
  the cap is in force; the forward curve is a STEP function (no smoothing).
- Fixed mode (the default) reproduces Run-4 outputs exactly.
- The cap premium is a levered financing cost at close (loanFees row).
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.services.proforma import debt, engine

FIXTURES = Path(__file__).parent / "fixtures"


def analytic(**overrides) -> dict:
    deal = json.loads((FIXTURES / "analytic_acquisition.json").read_text())
    deal.update(overrides)
    return deal


def floating(**over) -> dict:
    base = {
        "rateMode": "floating",
        "currentIndexPct": 0.04,
        "spreadBps": 200,
    }
    base.update(over)
    return analytic(**base)


def test_step_interpolation_no_smoothing():
    """Curve point at month 13 -> months 1-12 at the current index, 13+ at
    the point's index. 600,000 IO: 6% -> 3,000/mo, 7% -> 3,500/mo."""
    result = engine.compute(floating(forwardCurve=[{"month": 13, "indexPct": 0.05}]))
    stmt = result["statement"]
    assert stmt["debtService"][1] == pytest.approx(3_000)
    assert stmt["debtService"][12] == pytest.approx(3_000)  # step, not a ramp
    assert stmt["debtService"][13] == pytest.approx(3_500)
    assert stmt["debtService"][60] == pytest.approx(3_500)


def test_floor_binds():
    """Index 4% with a 4.5% floor -> all-in 6.5% -> 3,250/mo."""
    result = engine.compute(floating(floorPct=0.045))
    assert result["statement"]["debtService"][1] == pytest.approx(3_250)


def test_cap_binds_in_force_then_expires():
    """Index 6% + 200bps = 8% uncapped; strike 5% for 24 months -> all-in 7%
    (3,500/mo) through month 24, 8% (4,000/mo) from month 25."""
    result = engine.compute(
        floating(currentIndexPct=0.06, rateCapStrikePct=0.05, rateCapTermMonths=24)
    )
    stmt = result["statement"]
    assert stmt["debtService"][1] == pytest.approx(3_500)
    assert stmt["debtService"][24] == pytest.approx(3_500)
    assert stmt["debtService"][25] == pytest.approx(4_000)


def test_dscr_at_cap_strike_replaces_generic_stress():
    """Strike 5% + 200bps spread = 7% all-in on a pure-IO loan -> annual
    service 42,000 vs sizing NOI 80,000 -> DSCR 1.9048."""
    result = engine.compute(
        floating(currentIndexPct=0.06, rateCapStrikePct=0.05, rateCapTermMonths=24)
    )
    expected = 80_000 / (600_000 * 0.07)
    assert result["outputs"]["dscrAtCapStrike"] == pytest.approx(expected)
    cap = result["debt"]["rate"]["cap"]
    assert cap["strikeAllInPct"] == pytest.approx(0.07)
    assert cap["dscrAtStrike"] == pytest.approx(expected)


def test_cap_premium_is_levered_cost_at_close():
    result = engine.compute(
        floating(rateCapStrikePct=0.05, rateCapTermMonths=24, rateCapPremium=10_000)
    )
    stmt = result["statement"]
    # Equity funds the premium; the property (unlevered) never sees it.
    assert stmt["levered"][0] == pytest.approx(-410_000)
    assert stmt["loanFees"][0] == pytest.approx(10_000)
    assert result["outputs"]["ltc"] == pytest.approx(600_000 / 1_010_000)
    uses = dict(result["sourcesAndUses"]["uses"])
    assert uses["Rate cap premium"] == pytest.approx(10_000)


def test_fixed_default_reproduces_run4():
    plain = engine.compute(analytic())
    # Floating inputs present but rateMode fixed -> completely inert.
    explicit = engine.compute(
        analytic(rateMode="fixed", currentIndexPct=0.09, spreadBps=500,
                 forwardCurve=[{"month": 1, "indexPct": 0.10}])
    )
    assert plain["outputs"] == explicit["outputs"]
    assert "rate" not in (plain["debt"] or {})
    assert "dscrAtCapStrike" not in plain["outputs"]


def test_floating_amortization_matches_fixed_on_flat_vector():
    """A flat rate vector must reprice to exactly the level-payment schedule
    (the ARM convention degenerates to the fixed loan)."""
    fixed = debt.amortization_schedule(100_000, 0.06, 30, 0, 24)
    floating_sched = debt.amortization_schedule_floating(
        100_000, [0.06] * 24, 30, 0, 24
    )
    for a, b in zip(fixed, floating_sched):
        assert b.interest == pytest.approx(a.interest, abs=1e-9)
        assert b.principal == pytest.approx(a.principal, abs=1e-9)
        assert b.balance == pytest.approx(a.balance, abs=1e-9)


def test_construction_interest_honors_rate_vector():
    """100 drawn at month 0, no equity: month 1 accrues at 12%/yr (1.00),
    month 2 at 24%/yr on the grown balance (101 x 2% = 2.02)."""
    financing = debt.construction_financing(
        [100.0, 0.0, 0.0], 0.0, 0.12, rate_vector=[0.12, 0.24, 0.24]
    )
    assert financing.balances[1] == pytest.approx(101.0)
    assert financing.balances[2] == pytest.approx(101.0 * 1.02)
    assert financing.interest_capitalized == pytest.approx(1.0 + 2.02)


def test_forward_curve_round_trips_deal_save(client):
    deal = client.post("/api/deals", json={"name": "Floater"}).json()
    inputs = floating(
        forwardCurve=[{"month": 1, "indexPct": 0.043}, {"month": 25, "indexPct": 0.038}],
        rateCapStrikePct=0.05, rateCapTermMonths=36, rateCapPremium=25_000,
    )
    client.put(f"/api/deals/{deal['id']}", json={"inputs": inputs})
    fetched = client.get(f"/api/deals/{deal['id']}").json()
    assert fetched["inputs"]["forwardCurve"] == inputs["forwardCurve"]
    assert fetched["inputs"]["rateCapPremium"] == 25_000
