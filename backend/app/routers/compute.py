from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.services import compute_cache, goal_seek, monte_carlo, tornado_service
from app.services.proforma import engine, hold
from app.api_models import ComputeResponseOut

router = APIRouter(prefix="/api/compute", tags=["compute"])


class ComputeRequest(BaseModel):
    values: dict[str, Any]


class TornadoRequest(BaseModel):
    values: dict[str, Any]
    metric: str = "leveredIrr"


class GoalSeekRequest(BaseModel):
    values: dict[str, Any]
    targetInput: str
    outputMetric: str
    targetValue: float
    bounds: tuple[float, float] | None = None


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


@router.post("/goal-seek")
def goal_seek_endpoint(payload: GoalSeekRequest):
    """J7: solve one numeric input for a target output metric. A found
    solution and a typed no-solution are both 200s — the scan detail is the
    answer either way; only a malformed request is a 400."""
    try:
        return goal_seek.run_goal_seek(
            payload.values, payload.targetInput, payload.outputMetric,
            payload.targetValue, payload.bounds,
        )
    except goal_seek.GoalSeekError as exc:
        raise HTTPException(400, str(exc)) from exc
    except engine.InsufficientInputsError as exc:
        return JSONResponse(
            status_code=422, content={"detail": str(exc), "missing": exc.missing}
        )


@router.get("/goal-seek/inputs")
def goal_seek_inputs():
    """The searchable list of numeric schema inputs for the UI picker."""
    return [
        {"id": field_id, "label": field.get("label", field_id), "type": field["type"]}
        for field_id, field in goal_seek.numeric_input_fields().items()
    ]


class MonteCarloRequest(BaseModel):
    values: dict[str, Any]
    drivers: list[dict[str, Any]]
    correlations: list[dict[str, Any]] | None = None
    n: int = 500
    seed: int | None = None
    hurdleIrr: float = monte_carlo.DEFAULT_HURDLE


@router.post("/monte-carlo")
def monte_carlo_start(payload: MonteCarloRequest):
    """J8: start a seeded Monte Carlo run on a background thread. Validation
    is synchronous — a bad request fails HERE, not at the poll."""
    try:
        job_id = monte_carlo.start_job(
            payload.values, payload.drivers, payload.correlations,
            payload.n, payload.seed, payload.hurdleIrr,
        )
    except monte_carlo.MonteCarloError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"jobId": job_id, "n": payload.n}


@router.get("/monte-carlo/{job_id}")
def monte_carlo_poll(job_id: str):
    status = monte_carlo.job_status(job_id)
    if status is None:
        raise HTTPException(404, "Unknown Monte Carlo job — it may have been evicted.")
    return status


@router.post("", response_model=ComputeResponseOut)
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
    if result.get("gpEconomics"):
        # J3: conditional — only fee-carrying deals gain the block.
        response["gpEconomics"] = result["gpEconomics"]
    if result.get("juniorTranche"):
        # J4: conditional — only tranche deals gain the block.
        response["juniorTranche"] = result["juniorTranche"]
    if detail:
        # The period-level statement: the engine's own vectors, no recompute.
        response["statement"] = result["statement"]
    return response
