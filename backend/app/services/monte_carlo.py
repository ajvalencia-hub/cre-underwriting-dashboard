"""J8: Monte Carlo simulation over the native engine.

Drivers are numeric schema inputs (the same registry goal-seek uses), each
with a marginal distribution (normal | triangular | uniform). Correlations
are applied with a GAUSSIAN COPULA: correlated standard normals via the
Cholesky factor of the pairwise correlation matrix, mapped through the
normal CDF to uniforms, then through each marginal's inverse CDF. numpy is
used for the linear algebra — it is already a transitive dependency of this
app (matplotlib pulls it in; it is NOT added to requirements.txt), which the
run rules permit. A non-positive-definite correlation matrix is a typed
error, never silently repaired.

Runs are seeded and deterministic. Each trial is one engine.compute with
`_skipCategoricalStress` set (the insurance-stress recomputes would triple
the cost for numbers nobody reads per-trial). Long runs execute on a
background thread with a polling job store.
"""

import logging
import math
import threading
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from app.services import goal_seek
from app.services.proforma import engine

MAX_DRIVERS = 6
MAX_RUNS = 2000
HISTOGRAM_BINS = 20
DEFAULT_HURDLE = 0.08
_MAX_JOBS = 20
# Each job is up to MAX_RUNS full engine computes. Runs execute on a small
# fixed pool (not one thread per POST) and the pool refuses new work past a
# queue depth — otherwise every click on "Run" spawned an unbounded CPU-bound
# thread that kept running even after its job entry was evicted.
_MAX_WORKERS = 2
_MAX_QUEUED = 4

_DISTRIBUTIONS = ("normal", "triangular", "uniform")

logger = logging.getLogger("app.monte_carlo")


class MonteCarloError(ValueError):
    """Bad request — invalid drivers, params, correlations, or run size."""


class MonteCarloBusy(RuntimeError):
    """The pool is saturated — the caller should retry later (429)."""


_jobs: "OrderedDict[str, dict]" = OrderedDict()
_jobs_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="monte-carlo")
_pending = 0  # queued + running, guarded by _jobs_lock


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_drivers(drivers: list[dict]) -> list[dict]:
    if not drivers:
        raise MonteCarloError("At least one driver is required.")
    if len(drivers) > MAX_DRIVERS:
        raise MonteCarloError(f"At most {MAX_DRIVERS} drivers are supported.")
    fields = goal_seek.numeric_input_fields()
    seen: set[str] = set()
    cleaned = []
    for d in drivers:
        path = d.get("inputPath")
        if path not in fields:
            raise MonteCarloError(f"'{path}' is not a numeric schema input.")
        if path in seen:
            raise MonteCarloError(f"Driver '{path}' appears more than once.")
        seen.add(path)
        dist = d.get("distribution")
        params = d.get("params") or {}

        def _p(key: str) -> float:
            value = params.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise MonteCarloError(
                    f"Driver '{path}' ({dist}) needs numeric param '{key}'."
                )
            return float(value)

        if dist == "normal":
            mean, std = _p("mean"), _p("stdDev")
            if std <= 0:
                raise MonteCarloError(f"Driver '{path}': stdDev must be > 0.")
            cleaned.append({"inputPath": path, "distribution": dist,
                            "params": {"mean": mean, "stdDev": std}})
        elif dist == "triangular":
            lo, mode, hi = _p("min"), _p("mode"), _p("max")
            if not (lo <= mode <= hi and lo < hi):
                raise MonteCarloError(
                    f"Driver '{path}': need min <= mode <= max and min < max."
                )
            cleaned.append({"inputPath": path, "distribution": dist,
                            "params": {"min": lo, "mode": mode, "max": hi}})
        elif dist == "uniform":
            lo, hi = _p("min"), _p("max")
            if not lo < hi:
                raise MonteCarloError(f"Driver '{path}': need min < max.")
            cleaned.append({"inputPath": path, "distribution": dist,
                            "params": {"min": lo, "max": hi}})
        else:
            raise MonteCarloError(
                f"Driver '{path}': distribution must be one of {_DISTRIBUTIONS}."
            )
    return cleaned


def _correlation_matrix(
    drivers: list[dict], correlations: list[dict] | None
) -> np.ndarray | None:
    if not correlations:
        return None
    index = {d["inputPath"]: i for i, d in enumerate(drivers)}
    k = len(drivers)
    matrix = np.eye(k)
    for pair in correlations:
        a, b = pair.get("a"), pair.get("b")
        rho = pair.get("rho")
        if a not in index or b not in index or a == b:
            raise MonteCarloError(
                f"Correlation pair ({a}, {b}) must name two distinct drivers."
            )
        if not isinstance(rho, (int, float)) or not -1 <= float(rho) <= 1:
            raise MonteCarloError(f"Correlation rho for ({a}, {b}) must be in [-1, 1].")
        matrix[index[a], index[b]] = matrix[index[b], index[a]] = float(rho)
    try:
        np.linalg.cholesky(matrix)
    except np.linalg.LinAlgError as exc:
        raise MonteCarloError(
            "The correlation matrix is not positive definite — the pairwise "
            "correlations are jointly inconsistent."
        ) from exc
    return matrix


# ---------------------------------------------------------------------------
# Sampling (Gaussian copula)
# ---------------------------------------------------------------------------

def _inverse_cdf(dist: str, params: dict, u: float) -> float:
    if dist == "uniform":
        return params["min"] + (params["max"] - params["min"]) * u
    # triangular
    lo, mode, hi = params["min"], params["mode"], params["max"]
    split = (mode - lo) / (hi - lo) if hi > lo else 0.0
    if u <= split:
        return lo + math.sqrt(u * (hi - lo) * (mode - lo))
    return hi - math.sqrt((1 - u) * (hi - lo) * (hi - mode))


def sample_matrix(
    drivers: list[dict], corr: np.ndarray | None, n: int, seed: int
) -> list[list[float]]:
    """n × k driver samples, deterministic for a seed. Normal marginals use
    the correlated normals directly (exact); uniform/triangular go through
    the copula's uniforms."""
    k = len(drivers)
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((n, k))
    if corr is not None:
        z = z @ np.linalg.cholesky(corr).T
    rows: list[list[float]] = []
    for i in range(n):
        row = []
        for j, driver in enumerate(drivers):
            params = driver["params"]
            if driver["distribution"] == "normal":
                row.append(params["mean"] + params["stdDev"] * float(z[i, j]))
            else:
                u = 0.5 * (1 + math.erf(float(z[i, j]) / math.sqrt(2)))
                # Clamp away from exact 0/1 so inverse CDFs stay finite.
                u = min(max(u, 1e-12), 1 - 1e-12)
                row.append(_inverse_cdf(driver["distribution"], params, u))
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def _percentiles(sorted_values: list[float]) -> dict:
    arr = np.array(sorted_values)
    return {
        "p5": float(np.percentile(arr, 5)),
        "p25": float(np.percentile(arr, 25)),
        "p50": float(np.percentile(arr, 50)),
        "p75": float(np.percentile(arr, 75)),
        "p95": float(np.percentile(arr, 95)),
        "mean": float(arr.mean()),
        "min": float(arr.min()),
        "max": float(arr.max()),
    }


def _histogram(values: list[float]) -> list[dict]:
    counts, edges = np.histogram(np.array(values), bins=HISTOGRAM_BINS)
    return [
        {"lo": float(edges[i]), "hi": float(edges[i + 1]), "count": int(counts[i])}
        for i in range(len(counts))
    ]


def run_simulation(
    values: dict,
    drivers: list[dict],
    correlations: list[dict] | None = None,
    n: int = 500,
    seed: int | None = None,
    hurdle_irr: float = DEFAULT_HURDLE,
    progress: dict | None = None,
) -> dict:
    """Synchronous core. `progress`, when given, gets 'completed' bumped per
    trial (the job store passes its own dict)."""
    if not isinstance(n, int) or n < 1 or n > MAX_RUNS:
        raise MonteCarloError(f"n must be an integer in 1 .. {MAX_RUNS}.")
    cleaned = _validate_drivers(drivers)
    corr = _correlation_matrix(cleaned, correlations)
    if seed is None:
        seed = int.from_bytes(uuid.uuid4().bytes[:4], "big")

    samples = sample_matrix(cleaned, corr, n, seed)
    irrs: list[float] = []
    multiples: list[float] = []
    peaks: list[float] = []
    failed = 0
    for row in samples:
        trial = {**values, "_skipCategoricalStress": True}
        for driver, value in zip(cleaned, row, strict=False):
            trial[driver["inputPath"]] = value
        try:
            result = engine.compute(trial)
            outputs = result["outputs"]
            irr = outputs.get("leveredIrr")
            multiple = outputs.get("equityMultiple")
            if not isinstance(irr, (int, float)) or not isinstance(multiple, (int, float)):
                raise ValueError("metric missing")
            levered = result["statement"]["levered"]
            # Peak negative cash flow: the worst levered month AFTER close
            # (0 when no month goes negative) — the capital-call question;
            # the close-month equity check is known, not risk.
            peak = min(0.0, min(levered[1:])) if len(levered) > 1 else 0.0
            irrs.append(float(irr))
            multiples.append(float(multiple))
            peaks.append(float(peak))
        except (engine.InsufficientInputsError, ValueError, ZeroDivisionError):
            failed += 1
        if progress is not None:
            progress["completed"] = progress.get("completed", 0) + 1

    if not irrs:
        raise MonteCarloError(
            "Every trial failed to compute — the driver ranges likely push "
            "required inputs out of their valid domain."
        )

    return {
        "n": n,
        "seed": seed,
        "successfulRuns": len(irrs),
        "failedRuns": failed,
        "drivers": cleaned,
        "correlations": correlations or [],
        "hurdleIrr": hurdle_irr,
        "leveredIrr": _percentiles(sorted(irrs)),
        "equityMultiple": _percentiles(sorted(multiples)),
        "peakNegativeCashFlow": _percentiles(sorted(peaks)),
        "probIrrNegative": sum(1 for x in irrs if x < 0) / len(irrs),
        "probIrrBelowHurdle": sum(1 for x in irrs if x < hurdle_irr) / len(irrs),
        "histogram": {
            "leveredIrr": _histogram(irrs),
            "equityMultiple": _histogram(multiples),
        },
    }


# ---------------------------------------------------------------------------
# Background jobs (simple polling — no websockets)
# ---------------------------------------------------------------------------

def start_job(
    values: dict,
    drivers: list[dict],
    correlations: list[dict] | None,
    n: int,
    seed: int | None,
    hurdle_irr: float,
) -> str:
    """Validates SYNCHRONOUSLY (bad requests fail the POST, not the poll),
    then runs the simulation on a daemon thread."""
    if not isinstance(n, int) or n < 1 or n > MAX_RUNS:
        raise MonteCarloError(f"n must be an integer in 1 .. {MAX_RUNS}.")
    if seed is not None and (not isinstance(seed, int) or seed < 0 or seed >= 2**32):
        # numpy's Generator rejects negative seeds with a ValueError that used
        # to escape the worker and leave the job "running" forever.
        raise MonteCarloError("seed must be an integer in 0 .. 2^32-1.")
    cleaned = _validate_drivers(drivers)
    _correlation_matrix(cleaned, correlations)

    global _pending
    job_id = uuid.uuid4().hex[:12]
    job = {"status": "running", "completed": 0, "n": n, "result": None, "error": None}
    with _jobs_lock:
        if _pending >= _MAX_WORKERS + _MAX_QUEUED:
            raise MonteCarloBusy(
                "Too many Monte Carlo runs in flight — wait for one to finish and retry."
            )
        _pending += 1
        _jobs[job_id] = job
        while len(_jobs) > _MAX_JOBS:
            _jobs.popitem(last=False)

    def _run():
        global _pending
        try:
            job["result"] = run_simulation(
                values, cleaned, correlations, n, seed, hurdle_irr, progress=job
            )
            job["status"] = "done"
        except MonteCarloError as exc:
            job["error"] = str(exc)
            job["status"] = "failed"
        except Exception as exc:  # noqa: BLE001 — a job must never hang in "running"
            logger.exception("Monte Carlo job %s crashed", job_id)
            job["error"] = f"Simulation failed: {exc}"
            job["status"] = "failed"
        finally:
            with _jobs_lock:
                _pending -= 1

    _executor.submit(_run)
    return job_id


def pending_jobs() -> int:
    with _jobs_lock:
        return _pending


def job_status(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        return None
    out = {"status": job["status"], "completed": job["completed"], "n": job["n"]}
    if job["status"] == "done":
        out["result"] = job["result"]
    if job["status"] == "failed":
        out["error"] = job["error"]
    return out
