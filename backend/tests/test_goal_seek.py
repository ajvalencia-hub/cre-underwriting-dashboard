"""J7: generalized goal-seek — bracket scan + bisection, no monotonicity
assumption, metric-typed tolerances, compute-cache interplay."""

import json
from pathlib import Path

import pytest

from app.services import compute_cache, goal_seek
from app.services.proforma import engine

FIXTURES = Path(__file__).parent / "fixtures"


def analytic(**overrides) -> dict:
    deal = json.loads((FIXTURES / "analytic_acquisition.json").read_text())
    deal.update(overrides)
    return deal


def test_solve_price_for_levered_irr():
    """The analytic deal hits its known IRR at exactly 1,000,000 — start the
    input elsewhere and ask the solver to find its way back."""
    target_irr = engine.compute(analytic())["outputs"]["leveredIrr"]
    result = goal_seek.run_goal_seek(
        analytic(purchasePrice=1_100_000), "purchasePrice", "leveredIrr", target_irr
    )
    assert result["solvedValue"] == pytest.approx(1_000_000, rel=0.01)
    assert result["achievedMetric"] == pytest.approx(target_irr, abs=2e-5)
    assert result["iterations"] <= goal_seek.MAX_ITERATIONS
    assert result["tolerance"] == 1e-5  # percent metric -> 0.1bp


def test_solve_exit_cap_for_development_spread():
    """developmentSpreadBps = yieldOnCost − exitCap = 8% − cap on this deal:
    a 1% spread means a 7% exit cap, in closed form."""
    result = goal_seek.run_goal_seek(
        analytic(), "exitCapRatePct", "developmentSpreadBps", 0.01
    )
    assert result["solvedValue"] == pytest.approx(0.07, abs=1e-4)


def test_no_solution_is_typed_with_scan_detail():
    result = goal_seek.run_goal_seek(
        analytic(), "purchasePrice", "leveredIrr", 5.0  # 500% IRR: unreachable
    )
    assert result["solvedValue"] is None
    assert result["reason"] == "no_crossing"
    assert result["scannedRange"] == [200_000, 1_800_000]  # ±80% of current
    assert len(result["scanned"]) == goal_seek.SCAN_POINTS
    assert all("value" in p and "metric" in p for p in result["scanned"])


def test_multiple_crossings_returns_nearest_and_reports_others():
    """Parabola (v−1)(v−3): target 0 crosses at 1 and 3. Current input 3.5
    -> the solver must pick 3 and disclose the other crossing near 1."""
    result = goal_seek._solve(
        evaluate=lambda v: (v - 1) * (v - 3),
        current=3.5, lo=0.0, hi=4.0, target=0.0, tolerance=1e-6,
    )
    assert result["solvedValue"] == pytest.approx(3.0, abs=1e-3)
    assert len(result["otherCrossings"]) == 1
    assert result["otherCrossings"][0] == pytest.approx(1.0, abs=0.5)


def test_metric_gaps_break_brackets():
    """None points (metric unavailable) must not be treated as crossings."""
    result = goal_seek._solve(
        evaluate=lambda v: None if 1.5 < v < 2.5 else v - 2.0,
        current=0.0, lo=0.0, hi=4.0, target=0.0, tolerance=1e-6,
    )
    # The only sign change spans the None gap -> no valid bracket. (The scan
    # may still land exactly on 2.0 if a grid point hits it; with 12 points
    # over 0..4 the grid is 0, 0.3636... and never exactly 2.)
    assert result["solvedValue"] is None
    assert result["reason"] == "no_crossing"


def test_goal_seek_reuses_the_compute_cache():
    """The engine is pure and the eval sequence deterministic: re-running the
    same goal-seek must be answered entirely from cache."""
    compute_cache.clear()
    target_irr = engine.compute(analytic())["outputs"]["leveredIrr"]
    first = goal_seek.run_goal_seek(
        analytic(purchasePrice=1_100_000), "purchasePrice", "leveredIrr", target_irr
    )
    stats_after_first = compute_cache.cache_stats()
    second = goal_seek.run_goal_seek(
        analytic(purchasePrice=1_100_000), "purchasePrice", "leveredIrr", target_irr
    )
    stats_after_second = compute_cache.cache_stats()
    assert second["solvedValue"] == first["solvedValue"]
    # Zero new misses; every evaluation of the second run was a hit.
    assert stats_after_second["misses"] == stats_after_first["misses"]
    assert (
        stats_after_second["hits"] - stats_after_first["hits"] == first["iterations"]
    )


def test_bad_field_and_metric_raise_typed_errors():
    with pytest.raises(goal_seek.GoalSeekError):
        goal_seek.run_goal_seek(analytic(), "dealName", "leveredIrr", 0.1)
    with pytest.raises(goal_seek.GoalSeekError):
        goal_seek.run_goal_seek(analytic(), "purchasePrice", "notAMetric", 0.1)
