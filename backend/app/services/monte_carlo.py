"""L7: Monte Carlo simulation over the native engine. Orchestration only —
every dollar comes from engine.compute; this module's own math is limited
to sampling (see DECISIONS.md for the correlation-method [FIN]) and
percentile/histogram summarization.

Job execution (no websockets, per spec): POST kicks off a background
`threading.Thread` and returns a runId immediately; GET polls job status.
No new task-queue infrastructure — a plain in-memory dict is enough since
jobs don't need to survive a process restart.
"""

import copy
import math
import threading
import uuid
from collections import OrderedDict

import numpy as np

from app.services import compute_cache
from app.services.proforma import engine

MAX_DRAWS = 2000
MAX_DRIVERS = 6
MAX_JOBS = 50
HISTOGRAM_BINS = 20
_METRICS = ("leveredIrr", "equityMultiple", "peakNegativeCashFlow")

_jobs: "OrderedDict[str, dict]" = OrderedDict()
_lock = threading.Lock()


class MonteCarloValidationError(ValueError):
    pass


def _validate(drivers: list[dict], correlations: list[list[float]] | None, n: int) -> None:
    if n <= 0 or n > MAX_DRAWS:
        raise MonteCarloValidationError(f"n must be between 1 and {MAX_DRAWS}.")
    if not drivers:
        raise MonteCarloValidationError("At least one driver is required.")
    if len(drivers) > MAX_DRIVERS:
        raise MonteCarloValidationError(f"At most {MAX_DRIVERS} drivers are supported.")
    for d in drivers:
        if d.get("distribution") not in ("normal", "triangular", "uniform"):
            raise MonteCarloValidationError(f"Unknown distribution '{d.get('distribution')}'.")
        if not d.get("inputPath"):
            raise MonteCarloValidationError("Every driver needs an inputPath.")
    if correlations is not None:
        k = len(drivers)
        if len(correlations) != k or any(len(row) != k for row in correlations):
            raise MonteCarloValidationError(
                f"correlations must be a {k}x{k} matrix matching the driver count."
            )


def _norm_cdf(z: np.ndarray) -> np.ndarray:
    erf = np.vectorize(math.erf)
    return 0.5 * (1 + erf(z / math.sqrt(2)))


def _triangular_ppf(u: np.ndarray, low: float, mode: float, high: float) -> np.ndarray:
    fc = (mode - low) / (high - low) if high > low else 0.5
    out = np.empty_like(u)
    left = u < fc
    out[left] = low + np.sqrt(u[left] * (high - low) * (mode - low))
    out[~left] = high - np.sqrt((1 - u[~left]) * (high - low) * (high - mode))
    return out


def _sample_drivers(drivers: list[dict], correlations: list[list[float]] | None, n: int, seed: int) -> np.ndarray:
    """Returns an (n, k) array of sampled driver values.

    [FIN] correlation method (DECISIONS.md): a Gaussian copula — draw
    correlated standard normals via Cholesky decomposition of the
    correlation matrix (identity when uncorrelated), then map each column
    through its OWN distribution's inverse CDF. 'normal' drivers use the Z
    column directly (mean + stdDev*Z) rather than round-tripping through a
    uniform and back (skips an unnecessary erf/erfinv pair, zero precision
    cost since Z is already exactly standard normal). 'triangular'/
    'uniform' drivers go through Phi(Z) -> their own inverse CDF. This
    preserves rank correlation across every marginal shape without a scipy
    dependency (math.erf, vectorized, is the only special function needed)."""
    k = len(drivers)
    rng = np.random.default_rng(seed)
    corr = np.array(correlations, dtype=float) if correlations else np.eye(k)
    z_independent = rng.standard_normal((n, k))
    chol = np.linalg.cholesky(corr)
    z = z_independent @ chol.T

    samples = np.empty((n, k))
    for i, driver in enumerate(drivers):
        params = driver.get("params") or {}
        dist = driver["distribution"]
        if dist == "normal":
            mean = float(params.get("mean", 0.0))
            std_dev = float(params.get("stdDev", 0.0))
            samples[:, i] = mean + std_dev * z[:, i]
        else:
            u = _norm_cdf(z[:, i])
            if dist == "uniform":
                lo, hi = float(params.get("min", 0.0)), float(params.get("max", 0.0))
                samples[:, i] = lo + u * (hi - lo)
            else:  # triangular
                lo = float(params.get("min", 0.0))
                mode = float(params.get("mode", (lo + float(params.get("max", lo))) / 2))
                hi = float(params.get("max", lo))
                samples[:, i] = _triangular_ppf(u, lo, mode, hi)
    return samples


def _percentile_summary(values: list[float]) -> dict | None:
    if not values:
        return None
    arr = np.array(values, dtype=float)
    pcts = np.percentile(arr, [5, 25, 50, 75, 95])
    return {
        "mean": float(arr.mean()),
        "p5": float(pcts[0]), "p25": float(pcts[1]), "p50": float(pcts[2]),
        "p75": float(pcts[3]), "p95": float(pcts[4]),
    }


def _histogram(values: list[float]) -> dict | None:
    if not values:
        return None
    counts, edges = np.histogram(np.array(values, dtype=float), bins=HISTOGRAM_BINS)
    return {"binEdges": edges.tolist(), "counts": counts.tolist()}


def _run_job(run_id: str, inputs: dict, drivers: list[dict], correlations, n: int, seed: int, hurdle_pct: float | None) -> None:  # noqa: E501
    try:
        samples = _sample_drivers(drivers, correlations, n, seed)
        metrics: dict[str, list[float]] = {m: [] for m in _METRICS}
        failed = 0

        for row in range(n):
            patched = copy.deepcopy(inputs)
            for i, driver in enumerate(drivers):
                patched[driver["inputPath"]] = float(samples[row, i])
            try:
                result = compute_cache.cached_compute(patched)
                irr = result["outputs"].get("leveredIrr")
                moic = result["outputs"].get("equityMultiple")
                levered = result["statement"]["levered"]
                peak_negative = min((c for c in levered if c < 0), default=0.0)
                if irr is not None:
                    metrics["leveredIrr"].append(irr)
                if moic is not None:
                    metrics["equityMultiple"].append(moic)
                metrics["peakNegativeCashFlow"].append(peak_negative)
            except engine.InsufficientInputsError:
                failed += 1

            with _lock:
                _jobs[run_id]["progress"]["completed"] = row + 1

        irr_values = metrics["leveredIrr"]
        prob_negative = (
            sum(1 for v in irr_values if v < 0) / len(irr_values) if irr_values else None
        )
        prob_below_hurdle = (
            sum(1 for v in irr_values if v < hurdle_pct) / len(irr_values)
            if irr_values and hurdle_pct is not None else None
        )

        result_payload = {
            "n": n, "failedDraws": failed,
            "distributions": {
                m: {"summary": _percentile_summary(vals), "histogram": _histogram(vals)}
                for m, vals in metrics.items()
            },
            "probabilityIrrBelowZero": prob_negative,
            "probabilityIrrBelowHurdle": prob_below_hurdle,
        }
        with _lock:
            _jobs[run_id]["status"] = "done"
            _jobs[run_id]["result"] = result_payload
    except Exception as exc:  # a failed job reports status, never crashes the thread silently
        with _lock:
            _jobs[run_id]["status"] = "error"
            _jobs[run_id]["error"] = str(exc)


def start_run(
    inputs: dict, drivers: list[dict], correlations: list[list[float]] | None,
    n: int, seed: int, hurdle_pct: float | None = None,
) -> str:
    _validate(drivers, correlations, n)
    run_id = uuid.uuid4().hex
    with _lock:
        _jobs[run_id] = {
            "status": "running",
            "progress": {"completed": 0, "total": n},
            "result": None,
            "error": None,
        }
        while len(_jobs) > MAX_JOBS:
            _jobs.popitem(last=False)
    thread = threading.Thread(
        target=_run_job, args=(run_id, inputs, drivers, correlations, n, seed, hurdle_pct), daemon=True,
    )
    thread.start()
    return run_id


def get_job(run_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(run_id)
        return copy.deepcopy(job) if job is not None else None
