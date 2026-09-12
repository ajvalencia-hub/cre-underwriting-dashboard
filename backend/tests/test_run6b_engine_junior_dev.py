"""Run 6 wave 2 [FIN]: a junior tranche on a development that never takes
out its permanent loan before exit would fund AND repay in the exit month
(net effect: its origination fee only). The engine now skips it with an
explicit warning — no funding, no interest, no fee."""

import json
from pathlib import Path

import pytest

from app.services.proforma import engine

FIXTURES = Path(__file__).parent / "fixtures"


def development(**overrides) -> dict:
    deal = json.loads((FIXTURES / "analytic_development.json").read_text())
    deal.update(overrides)
    return deal


MEZZ = {
    "juniorTrancheKind": "mezz",
    "juniorAmount": 500_000,
    "juniorRatePct": 0.12,
    "juniorPayMode": "current",
    "juniorOriginationFeePct": 0.02,
}


def test_tranche_that_would_fund_in_the_exit_month_is_skipped_with_warning():
    # Stabilization month 31 > a 30-month hold: no takeout before exit.
    base = engine.compute(development(holdPeriodYears=2.5))
    assert base["statement"]["stabilizationMonth"] > base["statement"]["exitMonth"]
    with_tranche = engine.compute(development(holdPeriodYears=2.5, **MEZZ))

    assert with_tranche["juniorTranche"] is None
    assert "juniorPayoff" not in with_tranche["statement"]
    assert "combinedLtv" not in with_tranche["outputs"]
    # No phantom fee: every levered dollar is identical to the no-tranche run.
    assert with_tranche["statement"]["levered"] == base["statement"]["levered"]
    assert with_tranche["outputs"] == base["outputs"]
    assert with_tranche["sourcesAndUses"] == base["sourcesAndUses"]
    assert any(
        "fund in the exit month" in w and "no origination fee" in w
        for w in with_tranche["warnings"]
    )


def test_tranche_sold_in_stabilization_month_is_also_skipped():
    """Hold ending IN the stabilization month (the refi-vs-sale 'sale' leg):
    B1 skips the takeout, so the tranche would also be same-month."""
    hold_years = 31 / 12
    base = engine.compute(development(holdPeriodYears=hold_years))
    assert base["statement"]["stabilizationMonth"] == base["statement"]["exitMonth"]
    with_tranche = engine.compute(development(holdPeriodYears=hold_years, **MEZZ))
    assert with_tranche["juniorTranche"] is None
    assert with_tranche["statement"]["levered"] == base["statement"]["levered"]
    assert any("fund in the exit month" in w for w in with_tranche["warnings"])


def test_tranche_with_a_real_takeout_still_funds():
    """Regression guard: the default 7-year hold takes out in month 31 and
    the tranche funds there, fee charged, as J4 specified."""
    result = engine.compute(development(**MEZZ))
    block = result["juniorTranche"]
    assert block is not None
    assert block["fundMonth"] == 31
    assert block["fee"] == pytest.approx(10_000)
    assert result["statement"]["juniorPayoff"][result["statement"]["exitMonth"]] > 0
    assert not any("fund in the exit month" in w for w in result["warnings"])
