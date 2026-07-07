from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.services import compute_cache, compute_solver, tornado_service
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
    if detail:
        # The period-level statement: the engine's own vectors, no recompute.
        response["statement"] = result["statement"]
    return response
