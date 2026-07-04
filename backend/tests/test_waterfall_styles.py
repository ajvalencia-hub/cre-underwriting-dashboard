"""G1: American vs European waterfall styles, the GP catch-up tier, and the
XIRR / periodic-monthly IRR convention — every expectation hand-computed
(arithmetic in the comments; the monthly hurdle (1+h)^(1/12)-1 makes annual
compounding exact at 12-month boundaries, so the numbers work out to cents).
"""

import json
from datetime import date
from pathlib import Path

import pytest

from app.services.proforma import returns
from app.services.proforma.equity import run_waterfall
from app.services.proforma import engine

FIXTURES = Path(__file__).parent / "fixtures"

# Shared fixture: -1000 at close, +1500 at month 12. LP 90 / GP 10,
# pref 8%, one promote tier {hurdle 12%, LP 70 / GP 30}.
FLOWS_1500 = [-1000.0] + [0.0] * 11 + [1500.0]
TIER = [{"irrHurdle": 0.12, "lpSplitAboveHurdle": 0.7, "gpSplitAboveHurdle": 0.3}]


def _run(flows, style="european", catch_up=None, tiers=TIER):
    return run_waterfall(
        flows, lp_share=0.9, gp_share=0.1, preferred_return=0.08,
        tiers=tiers, style=style, catch_up_pct=catch_up,
    )


def test_european_two_band_promote_hand_computed():
    """European on FLOWS_1500:
    - pref band: LP must reach 8% IRR => LP needs 900*1.08 = 972 at m12;
      band total = 972/0.9 = 1080 (LP 972, GP 108).
    - to first hurdle: LP needs 900*1.12 = 1008 => 36 more; band = 36/0.9
      = 40 (LP 36, GP 4). Cumulative 1120.
    - residual 380 at 70/30: LP 266, GP 114.
    LP total = 972+36+266 = 1274; GP = 108+4+114 = 226.
    LP IRR = 1274/900 - 1 = 0.415556; GP IRR = 226/100 - 1 = 1.26.
    promotePaid = (4 - 40*0.1) + (114 - 380*0.1) = 0 + 76 = 76."""
    wf = _run(FLOWS_1500, style="european")
    assert sum(wf["lpFlows"][1:]) == pytest.approx(1274.0, rel=1e-9)
    assert sum(wf["gpFlows"][1:]) == pytest.approx(226.0, rel=1e-9)
    assert wf["lpIrr"] == pytest.approx(1274 / 900 - 1, abs=1e-9)
    assert wf["gpIrr"] == pytest.approx(1.26, abs=1e-9)
    assert wf["promotePaid"] == pytest.approx(76.0, rel=1e-9)


def test_american_promote_starts_after_pref_and_roc_hand_computed():
    """American on the SAME flows:
    - accrued pref at m12 (monthly compounding at 1.08^(1/12)-1 for 12
      months = exactly 8%): LP 900*0.08 = 72, GP 100*0.08 = 8; paid first.
    - return of capital: LP 900, GP 100.
    - residual 1500-80-1000 = 420 goes straight to tier-1 splits (the
      deal-by-deal convention: promote crystallizes over the pref; tier 1's
      hurdle is satisfied by pref + full capital return): LP 294, GP 126.
    LP total = 72+900+294 = 1266; GP = 8+100+126 = 234.
    LP IRR = 1266/900 - 1 = 0.406667; GP IRR = 234/100 - 1 = 1.34.
    promotePaid = 126 - 420*0.1 = 84."""
    wf = _run(FLOWS_1500, style="american")
    assert sum(wf["lpFlows"][1:]) == pytest.approx(1266.0, rel=1e-9)
    assert sum(wf["gpFlows"][1:]) == pytest.approx(234.0, rel=1e-9)
    assert wf["lpIrr"] == pytest.approx(1266 / 900 - 1, abs=1e-9)
    assert wf["gpIrr"] == pytest.approx(1.34, abs=1e-9)
    assert wf["promotePaid"] == pytest.approx(84.0, rel=1e-9)
    # The styles genuinely diverge on identical flows.
    eu = _run(FLOWS_1500, style="european")
    assert sum(wf["gpFlows"][1:]) > sum(eu["gpFlows"][1:])


def test_american_pref_compounds_monthly_on_the_ledger():
    """-1000 at close, one distribution at month 24 of exactly capital plus
    two years of compounded pref: LP claim = 900*1.08^2 = 1049.76, GP claim
    = 100*1.08^2 = 116.64, total 1166.40. Everything is consumed by pref +
    ROC — zero promote."""
    flows = [-1000.0] + [0.0] * 23 + [1166.40]
    wf = _run(flows, style="american")
    assert wf["lpFlows"][24] == pytest.approx(1049.76, rel=1e-9)
    assert wf["gpFlows"][24] == pytest.approx(116.64, rel=1e-9)
    assert wf["promotePaid"] == pytest.approx(0.0, abs=1e-6)


def test_full_catch_up_reaches_promote_share_of_all_profit():
    """European + 100% catch-up on FLOWS_1500:
    - pref band: 1080 (LP 972 profit 72, GP 108 profit 8).
    - catch-up (c=1.0, p=0.3): x solves 8 + x = 0.3*(80 + x) =>
      x = 16/0.7 = 22.857143, all to GP.
    - residual 1500-1080-22.857143 = 397.142857 at 70/30:
      LP 278.000, GP 119.142857.
    LP total = 972 + 278 = 1250; GP total = 108+22.857143+119.142857 = 250.
    Check: GP profit = 250-100 = 150 = 30% of the 500 total profit — the
    textbook full-catch-up outcome. promotePaid = 250 - 150(pro-rata) = 100."""
    wf = _run(FLOWS_1500, style="european", catch_up=1.0)
    assert sum(wf["lpFlows"][1:]) == pytest.approx(1250.0, rel=1e-9)
    assert sum(wf["gpFlows"][1:]) == pytest.approx(250.0, rel=1e-9)
    gp_profit = sum(wf["gpFlows"])  # net of the -100 contribution
    total_profit = sum(wf["lpFlows"]) + gp_profit
    assert gp_profit == pytest.approx(0.3 * total_profit, rel=1e-9)
    assert wf["promotePaid"] == pytest.approx(100.0, rel=1e-9)


def test_partial_catch_up_stops_short_of_target():
    """Distribution of 1090: the pref band takes 1080, leaving 10 — far less
    than the 22.857 the catch-up needs, so the GP receives all 10 (c=1.0)
    and stays under-caught-up."""
    flows = [-1000.0] + [0.0] * 11 + [1090.0]
    wf = _run(flows, style="european", catch_up=1.0)
    assert sum(wf["gpFlows"][1:]) == pytest.approx(118.0, rel=1e-9)  # 108 pref-band + 10
    assert sum(wf["lpFlows"][1:]) == pytest.approx(972.0, rel=1e-9)
    gp_profit = sum(wf["gpFlows"])
    total_profit = sum(wf["lpFlows"]) + gp_profit
    assert gp_profit < 0.3 * total_profit  # target not reached


def test_unreachable_catch_up_pct_warns_and_is_skipped():
    wf = _run(FLOWS_1500, style="european", catch_up=0.2)  # <= tier-1 promote 0.3
    assert any("unreachable" in w for w in wf["warnings"])
    # Behaves exactly like the no-catch-up European run.
    baseline = _run(FLOWS_1500, style="european")
    assert sum(wf["gpFlows"][1:]) == pytest.approx(sum(baseline["gpFlows"][1:]), rel=1e-12)


def test_catch_up_without_tiers_warns():
    wf = _run(FLOWS_1500, style="european", catch_up=1.0, tiers=[])
    assert any("no promote tiers" in w for w in wf["warnings"])


# ------------------------------------------------------------------ IRR convention

@pytest.fixture
def analytic() -> dict:
    return json.loads((FIXTURES / "analytic_acquisition.json").read_text())


def test_xirr_agrees_with_periodic_on_clean_monthly_flows(analytic):
    """On an evenly-spaced monthly deal the two conventions differ only by
    calendar month-length noise — within 5bp on every IRR output."""
    periodic = engine.compute(analytic)
    xirr_run = engine.compute({**analytic, "irrConvention": "xirr"})
    assert periodic["irrConvention"] == "periodic_monthly"
    assert xirr_run["irrConvention"] == "xirr"
    for key in ("leveredIrr", "unleveredIrr", "lpIrr", "gpIrr"):
        if key in periodic["outputs"]:
            assert xirr_run["outputs"][key] == pytest.approx(
                periodic["outputs"][key], abs=0.0005
            ), key
    # Non-IRR metrics are convention-independent.
    assert xirr_run["outputs"]["equityMultiple"] == periodic["outputs"]["equityMultiple"]


def test_xirr_diverges_correctly_on_irregular_flows():
    """periodic_irr has no idea two flows are three years apart — it sees
    'month 1' and 'month 2'. XIRR dates them: [-1000, +800 after one month,
    +400 after three years] has a far lower true annual return than the
    periodic reading of the same undated vector."""
    amounts = [-1000.0, 800.0, 400.0]
    dated = returns.xirr(
        [date(2026, 1, 1), date(2026, 2, 1), date(2029, 1, 1)], amounts
    )
    undated = returns.periodic_irr(amounts)
    assert dated is not None and undated is not None
    assert dated < undated
    assert undated - dated > 0.5  # not subtle — years vs months of discounting


def test_engine_defaults_preserve_run1_behavior(analytic):
    """No irrConvention/waterfallStyle inputs => periodic + european, and the
    engine reports both so the UI/memo can footnote them."""
    result = engine.compute(analytic)
    assert result["irrConvention"] == "periodic_monthly"
    assert result["waterfallStyle"] == "european"
