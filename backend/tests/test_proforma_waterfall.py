"""F2: LP/GP waterfall — hand-calculated single-distribution promote case,
pro-rata behavior without tiers, and split normalization warnings.
"""

import pytest

from app.services.proforma.equity import run_waterfall


def _flows(contribution: float, distribution: float, months: int = 12) -> list[float]:
    flows = [0.0] * (months + 1)
    flows[0] = -contribution
    flows[months] = distribution
    return flows


def test_promote_hand_calc_single_distribution_at_one_year():
    """1,000 in at t0 (LP 900 / GP 100); 1,300 out at month 12.
    Pref 8%: LP made whole to 900 x 1.08 = 972 pro-rata -> band total 1,080.
    To the 10% hurdle: LP 972 -> 990 pro-rata -> band total 20.
    Residual 200 at 70/30 -> LP 140 / GP 60.
    Totals: LP 1,130, GP 170; promote = 200 x (30% - 10%) = 40."""
    result = run_waterfall(
        _flows(1000, 1300),
        lp_share=0.9,
        gp_share=0.1,
        preferred_return=0.08,
        tiers=[{"irrHurdle": 0.10, "lpSplitAboveHurdle": 0.7, "gpSplitAboveHurdle": 0.3}],
    )
    assert result["lpFlows"][12] == pytest.approx(1130, abs=0.01)
    assert result["gpFlows"][12] == pytest.approx(170, abs=0.01)
    assert result["promotePaid"] == pytest.approx(40, abs=0.01)
    # LP put in 900, got 1,130 at exactly one year -> IRR = 1130/900 - 1.
    assert result["lpIrr"] == pytest.approx(1130 / 900 - 1, abs=1e-6)
    assert result["gpIrr"] == pytest.approx(170 / 100 - 1, abs=1e-6)


def test_distribution_below_pref_is_all_pro_rata():
    result = run_waterfall(
        _flows(1000, 1000),  # exactly return of capital, no profit
        lp_share=0.9,
        gp_share=0.1,
        preferred_return=0.08,
        tiers=[{"irrHurdle": 0.10, "lpSplitAboveHurdle": 0.7, "gpSplitAboveHurdle": 0.3}],
    )
    assert result["lpFlows"][12] == pytest.approx(900)
    assert result["gpFlows"][12] == pytest.approx(100)
    assert result["promotePaid"] == 0.0


def test_no_tiers_means_everything_pro_rata():
    result = run_waterfall(_flows(1000, 2000), 0.9, 0.1, 0.08, tiers=[])
    assert result["lpFlows"][12] == pytest.approx(1800)
    assert result["gpFlows"][12] == pytest.approx(200)
    assert result["lpIrr"] == pytest.approx(result["gpIrr"], abs=1e-9)
    assert result["lpMultiple"] == pytest.approx(2.0)


def test_multi_event_distributions_conserve_cash():
    flows = [0.0] * 25
    flows[0] = -1000
    for m in range(1, 25):
        flows[m] = 30.0
    flows[24] += 1400
    result = run_waterfall(
        flows, 0.9, 0.1, 0.08,
        tiers=[
            {"irrHurdle": 0.12, "lpSplitAboveHurdle": 0.8, "gpSplitAboveHurdle": 0.2},
            {"irrHurdle": 0.18, "lpSplitAboveHurdle": 0.6, "gpSplitAboveHurdle": 0.4},
        ],
    )
    total_distributed = sum(cf for cf in flows if cf > 0)
    lp_dist = sum(cf for cf in result["lpFlows"] if cf > 0)
    gp_dist = sum(cf for cf in result["gpFlows"] if cf > 0)
    assert lp_dist + gp_dist == pytest.approx(total_distributed, abs=1e-6)
    # The GP earned promote, so its IRR must exceed the LP's.
    assert result["gpIrr"] > result["lpIrr"]


def test_split_normalization_and_zero_split_warnings():
    result = run_waterfall(
        _flows(1000, 1500), 0.85, 0.05, 0.08,  # sums to 0.9, not 1
        tiers=[{"irrHurdle": 0.10, "lpSplitAboveHurdle": 0, "gpSplitAboveHurdle": 0}],
    )
    assert any("normalized" in w for w in result["warnings"])
    assert any("zero splits" in w for w in result["warnings"])
    total_out = sum(cf for cf in result["lpFlows"] if cf > 0) + sum(
        cf for cf in result["gpFlows"] if cf > 0
    )
    assert total_out == pytest.approx(1500, abs=1e-6)
