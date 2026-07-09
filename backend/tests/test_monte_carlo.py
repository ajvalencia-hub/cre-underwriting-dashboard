"""L7: Monte Carlo. Two layers: pure unit tests on monte_carlo.py's
sampling/summarization math, and integration tests on the background-job
lifecycle (start_run -> polling get_job to completion) against the real
engine."""

import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import monte_carlo

FIXTURE = {
    "dealName": "MC Test",
    "dealType": "acquisition",
    "propertyType": "multifamily",
    "purchasePrice": 1_000_000,
    "grossPotentialRent": 100_000,
    "vacancyPct": 0.10,
    "creditLossPct": 0.02,
    "realEstateTaxes": 10_000,
    "holdPeriodYears": 5,
    "exitCapRatePct": 0.08,
    "ltvOrLtc": 0.6,
    "interestRate": 0.06,
    "amortYears": 30,
    "ioMonths": 60,
    "lpSplitPct": 0.9,
    "gpSplitPct": 0.1,
    "preferredReturnPct": 0.08,
}


def _wait_for_completion(run_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = monte_carlo.get_job(run_id)
        if job["status"] != "running":
            return job
        time.sleep(0.02)
    raise TimeoutError(f"Monte Carlo run {run_id} did not finish in {timeout}s")


# ----------------------------------------------------------------------
# Pure sampling/summarization math
# ----------------------------------------------------------------------

def test_triangular_ppf_hand_computed():
    # low=0, mode=5, high=10 -> F(mode) = 0.5. u=0.5 lands exactly at mode.
    u = np.array([0.0, 0.5, 1.0])
    result = monte_carlo._triangular_ppf(u, 0.0, 5.0, 10.0)
    assert result == pytest.approx([0.0, 5.0, 10.0])


def test_norm_cdf_matches_known_values():
    z = np.array([0.0, 1.959964, -1.959964])
    result = monte_carlo._norm_cdf(z)
    assert result == pytest.approx([0.5, 0.975, 0.025], abs=1e-4)


def test_percentile_summary_on_known_distribution():
    values = list(range(1, 101))  # 1..100
    summary = monte_carlo._percentile_summary(values)
    assert summary["p50"] == pytest.approx(50.5, abs=0.6)
    assert summary["mean"] == pytest.approx(50.5)
    assert summary["p5"] < summary["p25"] < summary["p50"] < summary["p75"] < summary["p95"]


def test_histogram_bins_sum_to_n():
    values = list(np.random.default_rng(1).normal(size=500))
    hist = monte_carlo._histogram(values)
    assert len(hist["counts"]) == monte_carlo.HISTOGRAM_BINS
    assert sum(hist["counts"]) == 500


def test_sample_drivers_normal_moments():
    drivers = [{"inputPath": "x", "distribution": "normal", "params": {"mean": 0.10, "stdDev": 0.02}}]
    samples = monte_carlo._sample_drivers(drivers, None, 5000, seed=42)
    assert samples[:, 0].mean() == pytest.approx(0.10, abs=0.005)
    assert samples[:, 0].std() == pytest.approx(0.02, abs=0.002)


def test_sample_drivers_uniform_bounds():
    drivers = [{"inputPath": "x", "distribution": "uniform", "params": {"min": 0.04, "max": 0.06}}]
    samples = monte_carlo._sample_drivers(drivers, None, 2000, seed=1)
    assert samples[:, 0].min() >= 0.04
    assert samples[:, 0].max() <= 0.06
    assert samples[:, 0].mean() == pytest.approx(0.05, abs=0.002)


def test_sample_drivers_preserves_correlation():
    drivers = [
        {"inputPath": "a", "distribution": "normal", "params": {"mean": 0.0, "stdDev": 1.0}},
        {"inputPath": "b", "distribution": "normal", "params": {"mean": 0.0, "stdDev": 1.0}},
    ]
    samples = monte_carlo._sample_drivers(drivers, [[1.0, 0.9], [0.9, 1.0]], 5000, seed=7)
    corr = np.corrcoef(samples[:, 0], samples[:, 1])[0, 1]
    assert corr == pytest.approx(0.9, abs=0.03)


def test_sample_drivers_deterministic_with_same_seed():
    drivers = [{"inputPath": "x", "distribution": "triangular", "params": {"min": 0, "mode": 5, "max": 10}}]
    a = monte_carlo._sample_drivers(drivers, None, 100, seed=123)
    b = monte_carlo._sample_drivers(drivers, None, 100, seed=123)
    assert np.array_equal(a, b)


# ----------------------------------------------------------------------
# Job lifecycle / validation
# ----------------------------------------------------------------------

def test_validation_rejects_too_many_drivers():
    drivers = [{"inputPath": f"f{i}", "distribution": "uniform", "params": {"min": 0, "max": 1}} for i in range(7)]
    with pytest.raises(monte_carlo.MonteCarloValidationError):
        monte_carlo.start_run(FIXTURE, drivers, None, 10, seed=1)


def test_validation_rejects_n_too_large():
    drivers = [{"inputPath": "vacancyPct", "distribution": "uniform", "params": {"min": 0.05, "max": 0.1}}]
    with pytest.raises(monte_carlo.MonteCarloValidationError):
        monte_carlo.start_run(FIXTURE, drivers, None, 2001, seed=1)


def test_validation_rejects_mismatched_correlation_matrix():
    drivers = [{"inputPath": "vacancyPct", "distribution": "uniform", "params": {"min": 0.05, "max": 0.1}}]
    with pytest.raises(monte_carlo.MonteCarloValidationError):
        monte_carlo.start_run(FIXTURE, drivers, [[1.0, 0.5], [0.5, 1.0]], 10, seed=1)


def test_job_starts_running_then_completes():
    drivers = [{"inputPath": "vacancyPct", "distribution": "normal", "params": {"mean": 0.10, "stdDev": 0.02}}]
    run_id = monte_carlo.start_run(FIXTURE, drivers, None, 30, seed=5)
    job = monte_carlo.get_job(run_id)
    assert job["status"] in ("running", "done")  # tiny n -> may finish before this read
    assert job["progress"]["total"] == 30

    done = _wait_for_completion(run_id)
    assert done["status"] == "done"
    assert done["progress"]["completed"] == 30
    assert done["result"]["n"] == 30
    assert done["result"]["distributions"]["leveredIrr"]["summary"] is not None
    assert done["result"]["distributions"]["leveredIrr"]["histogram"]["counts"]
    assert 0.0 <= done["result"]["probabilityIrrBelowZero"] <= 1.0


def test_job_run_seeded_determinism():
    drivers = [
        {"inputPath": "vacancyPct", "distribution": "normal", "params": {"mean": 0.10, "stdDev": 0.02}},
        {"inputPath": "exitCapRatePct", "distribution": "triangular", "params": {"min": 0.06, "mode": 0.08, "max": 0.10}},  # noqa: E501
    ]
    run_a = monte_carlo.start_run(FIXTURE, drivers, None, 40, seed=99)
    run_b = monte_carlo.start_run(FIXTURE, drivers, None, 40, seed=99)
    result_a = _wait_for_completion(run_a)["result"]
    result_b = _wait_for_completion(run_b)["result"]
    assert result_a["distributions"]["leveredIrr"]["summary"] == result_b["distributions"]["leveredIrr"]["summary"]


def test_hurdle_probability_computed_when_requested():
    drivers = [{"inputPath": "vacancyPct", "distribution": "normal", "params": {"mean": 0.10, "stdDev": 0.02}}]
    run_id = monte_carlo.start_run(FIXTURE, drivers, None, 30, seed=3, hurdle_pct=0.15)
    result = _wait_for_completion(run_id)["result"]
    assert result["probabilityIrrBelowHurdle"] is not None


def test_unknown_run_id_returns_none():
    assert monte_carlo.get_job("does-not-exist") is None


# ----------------------------------------------------------------------
# HTTP surface
# ----------------------------------------------------------------------

def test_post_monte_carlo_starts_and_get_polls_to_done():
    client = TestClient(app)
    response = client.post(
        "/api/compute/monte-carlo",
        json={
            "inputs": FIXTURE,
            "drivers": [
                {"inputPath": "vacancyPct", "distribution": "normal", "params": {"mean": 0.10, "stdDev": 0.02}},
            ],
            "n": 25,
            "seed": 11,
        },
    )
    assert response.status_code == 200
    run_id = response.json()["runId"]

    deadline = time.time() + 10
    status = None
    while time.time() < deadline:
        poll = client.get(f"/api/compute/monte-carlo/{run_id}")
        assert poll.status_code == 200
        status = poll.json()
        if status["status"] != "running":
            break
        time.sleep(0.02)
    assert status["status"] == "done"
    assert status["result"]["n"] == 25


def test_post_monte_carlo_rejects_too_many_drivers_with_422():
    client = TestClient(app)
    drivers = [
        {"inputPath": f"f{i}", "distribution": "uniform", "params": {"min": 0, "max": 1}} for i in range(7)
    ]
    response = client.post(
        "/api/compute/monte-carlo", json={"inputs": FIXTURE, "drivers": drivers, "n": 10, "seed": 1},
    )
    assert response.status_code == 422


def test_post_monte_carlo_rejects_n_over_cap_with_422():
    client = TestClient(app)
    drivers = [{"inputPath": "vacancyPct", "distribution": "uniform", "params": {"min": 0.05, "max": 0.1}}]
    response = client.post(
        "/api/compute/monte-carlo", json={"inputs": FIXTURE, "drivers": drivers, "n": 2001, "seed": 1},
    )
    assert response.status_code == 422


def test_get_monte_carlo_unknown_run_returns_404():
    client = TestClient(app)
    response = client.get("/api/compute/monte-carlo/does-not-exist")
    assert response.status_code == 404


def test_excel_export_never_blocks_monte_carlo_fields():
    from app.services.excel_model_export import unsupported_features

    # Monte Carlo is a separate compute mode -- it never touches the
    # exporter's input surface or refusal list at all (no MC-specific
    # fields exist on the deal inputs themselves).
    assert unsupported_features(FIXTURE) == []
