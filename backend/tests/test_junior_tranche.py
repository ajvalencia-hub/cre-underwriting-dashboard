"""J4: junior tranche (mezzanine / preferred equity).

Base fixture = the analytic acquisition: NOI 6,666.67/mo, senior IO
600,000 at 6% (service 3,000/mo), equity 400,000, 60-month hold, exit at
par (terminal 1,000,000, senior payoff 600,000, net proceeds 400,000).

Hand numbers for a $100,000 mezz at 12% (1%/mo):
  current pay:  interest 1,000/mo, operating cash 3,666.67/mo covers it;
                equity at close 300,000; payoff at exit 100,000
  accrued PIK:  balance(m) = 100,000 x 1.01^m; payoff = 100,000 x 1.01^60
                = 181,669.67
"""

import json
from pathlib import Path

import pytest

from app.services.proforma import engine

FIXTURES = Path(__file__).parent / "fixtures"


def analytic(**overrides) -> dict:
    deal = json.loads((FIXTURES / "analytic_acquisition.json").read_text())
    deal.update(overrides)
    return deal


def mezz(**over) -> dict:
    tranche = {
        "juniorTrancheKind": "mezz",
        "juniorAmount": 100_000,
        "juniorRatePct": 0.12,
        "juniorPayMode": "current",
        "juniorOriginationFeePct": 0,
    }
    tranche.update(over)
    return analytic(**tranche)


def test_current_pay_hand_numbers():
    result = engine.compute(mezz())
    stmt = result["statement"]
    # Funding reduces common equity at close: -400,000 + 100,000.
    assert stmt["levered"][0] == pytest.approx(-300_000)
    # 1,000/mo interest paid from operating cash after senior service.
    assert stmt["juniorInterest"][1] == pytest.approx(1_000)
    assert stmt["levered"][1] == pytest.approx(6_666.6667 - 3_000 - 1_000, abs=0.01)
    # Balance flat (no PIK), repaid at exit before common equity.
    assert stmt["juniorBalance"][59] == pytest.approx(100_000)
    assert stmt["juniorPayoff"][60] == pytest.approx(100_000)
    # Exit month: NOI + net proceeds - senior service - interest - payoff.
    assert stmt["levered"][60] == pytest.approx(
        6_666.6667 - 3_000 + 400_000 - 1_000 - 100_000, abs=0.01
    )
    assert result["juniorTranche"]["pikMonths"] == []


def test_accrued_pik_compounds_monthly():
    result = engine.compute(mezz(juniorPayMode="accrued"))
    stmt = result["statement"]
    # balance(m) = 100,000 x 1.01^m — pure monthly compounding.
    for m in (1, 12, 36):
        assert stmt["juniorBalance"][m] == pytest.approx(100_000 * 1.01 ** m), m
    payoff = 100_000 * 1.01 ** 60
    assert stmt["juniorPayoff"][60] == pytest.approx(payoff)
    # No current interest anywhere.
    assert all(v == 0 for v in stmt["juniorInterest"])
    # Operating months match the no-tranche deal exactly (PIK is silent).
    base = engine.compute(analytic())
    assert stmt["levered"][5] == pytest.approx(base["statement"]["levered"][5])


def test_fill_to_ltc_sizing():
    """Fill to 80% of cost: basis 1,000,000, senior 600,000 ->
    tranche = 0.8 x 1,000,000 - 600,000 = 200,000."""
    result = engine.compute(mezz(juniorAmount=0, juniorFillToLtcPct=0.80))
    assert result["juniorTranche"]["amount"] == pytest.approx(200_000)
    assert result["outputs"]["combinedLtc"] == pytest.approx(0.80)
    assert result["outputs"]["combinedLtv"] == pytest.approx(800_000 / 1_000_000)
    # Senior lender metrics untouched by the tranche.
    assert result["outputs"]["ltv"] == pytest.approx(0.60)


def test_current_pay_shortfall_converts_to_pik():
    """Rate 50% -> interest 4,166.67/mo vs 3,666.67 available: the 500
    shortfall PIKs and the balance grows."""
    result = engine.compute(mezz(juniorRatePct=0.50))
    stmt = result["statement"]
    assert 1 in result["juniorTranche"]["pikMonths"]
    assert stmt["juniorInterest"][1] == pytest.approx(3_666.6667, abs=0.01)
    assert stmt["juniorBalance"][1] == pytest.approx(100_000 + 500, abs=0.01)
    assert stmt["levered"][1] == pytest.approx(0, abs=0.01)  # swept to zero, never negative


def test_exit_priority_senior_then_tranche_then_equity():
    result = engine.compute(mezz())
    stmt = result["statement"]
    # Senior payoff is inside net sale proceeds (gross 1,000,000 - 600,000);
    # the tranche is then repaid; common equity keeps the rest.
    assert stmt["saleProceedsNet"][60] == pytest.approx(400_000)
    assert stmt["juniorPayoff"][60] == pytest.approx(100_000)
    equity_exit = stmt["levered"][60]
    assert equity_exit == pytest.approx(400_000 + 6_666.6667 - 3_000 - 1_000 - 100_000, abs=0.01)


def test_pref_equity_differs_in_labeling_only():
    mezz_result = engine.compute(mezz())
    pref_result = engine.compute(mezz(juniorTrancheKind="pref_equity"))
    assert pref_result["outputs"] == mezz_result["outputs"]
    assert pref_result["juniorTranche"]["kind"] == "pref_equity"
    label_sources = [name for name, _ in pref_result["sourcesAndUses"]["sources"]]
    assert "Preferred equity tranche" in label_sources


def test_defaults_reproduce_run4():
    plain = engine.compute(analytic())
    explicit = engine.compute(analytic(juniorTrancheKind="none", juniorAmount=0,
                                       juniorRatePct=0.12))
    assert plain["outputs"] == explicit["outputs"]
    assert plain["juniorTranche"] is None
    assert "juniorInterest" not in plain["statement"]
