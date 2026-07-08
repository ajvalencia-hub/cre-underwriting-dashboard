from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.services import compute_cache, compute_solver, monte_carlo, tornado_service
from app.services.proforma import engine, hold

router = APIRouter(prefix="/api/compute", tags=["compute"])


class ComputeRequest(BaseModel):
    values: dict[str, Any]


class TornadoRequest(BaseModel):
    values: dict[str, Any]
    metric: str = "leveredIrr"


class SolveRequest(BaseModel):
    values: dict[str, Any]
    targetField: str
    targetMetric: str
    targetValue: float
    lowerBound: float
    upperBound: float
    tolerance: float = 1e-4
    maxIterations: int = 50


class MonteCarloDriver(BaseModel):
    inputPath: str
    distribution: str
    params: dict[str, float] = {}


class MonteCarloRequest(BaseModel):
    inputs: dict[str, Any]
    drivers: list[MonteCarloDriver]
    correlations: list[list[float]] | None = None
    n: int = 500
    seed: int = 0
    hurdlePct: float | None = None


@router.post("/hold-sweep")
def hold_sweep(payload: ComputeRequest):
    try:
        sweep = hold.hold_sweep(payload.values)
        fork = hold.refi_vs_sale(payload.values)
    except engine.InsufficientInputsError as exc:
        return JSONResponse(
            status_code=422, content={"detail": str(exc), "missing": exc.missing}
        )
    return {"sweep": sweep, "refiVsSale": fork}


@router.post("/tornado")
def tornado(payload: TornadoRequest):
    try:
        return tornado_service.run_tornado(payload.values, payload.metric)
    except engine.InsufficientInputsError as exc:
        return JSONResponse(
            status_code=422, content={"detail": str(exc), "missing": exc.missing}
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/solve")
def solve(payload: SolveRequest):
    try:
        return compute_solver.solve(
            payload.values,
            payload.targetField,
            payload.targetMetric,
            payload.targetValue,
            payload.lowerBound,
            payload.upperBound,
            payload.tolerance,
            payload.maxIterations,
        )
    except engine.InsufficientInputsError as exc:
        return JSONResponse(
            status_code=422, content={"detail": str(exc), "missing": exc.missing}
        )
    except (compute_solver.SolveOutOfRangeError, compute_solver.SolveNoConvergenceError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("")
def compute(payload: ComputeRequest, detail: bool = False):
    try:
        # H13: LRU-cached — the engine is pure, and scenario comparisons /
        # repeated recalcs of unchanged inputs are common.
        result = compute_cache.cached_compute(payload.values)
    except engine.InsufficientInputsError as exc:
        return JSONResponse(
            status_code=422,
            content={"detail": str(exc), "missing": exc.missing},
        )
    response = {
        "outputs": result["outputs"],
        "warnings": result["warnings"],
        "debt": result["debt"],
        "irrConvention": result["irrConvention"],
        "waterfallStyle": result["waterfallStyle"],
    }
    if result["juniorTranche"] is not None:
        # L4: omitted (not null) when inactive — an opt-in feature, not a
        # core always-relevant metric, so it must never appear as a new key
        # in the byte-identical-reproduction regression baseline.
        response["juniorTranche"] = result["juniorTranche"]
    if detail:
        # The period-level statement: the engine's own vectors, no recompute.
        response["statement"] = result["statement"]
    return response


@router.post("/monte-carlo")
def monte_carlo_start(payload: MonteCarloRequest):
    try:
        # A quick base compute up front — the same InsufficientInputsError
        # contract as every other endpoint here, checked BEFORE spawning the
        # background thread rather than surfacing as a same-shaped error
        # buried in every failed draw.
        engine.compute(payload.inputs)
    except engine.InsufficientInputsError as exc:
        return JSONResponse(
            status_code=422, content={"detail": str(exc), "missing": exc.missing}
        )
    try:
        run_id = monte_carlo.start_run(
            payload.inputs,
            [d.model_dump() for d in payload.drivers],
            payload.correlations,
            payload.n,
            payload.seed,
            payload.hurdlePct,
        )
    except monte_carlo.MonteCarloValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"runId": run_id}


@router.get("/monte-carlo/{run_id}")
def monte_carlo_status(run_id: str):
    job = monte_carlo.get_job(run_id)
    if job is None:
        raise HTTPException(404, "Unknown Monte Carlo run id.")
    return job
