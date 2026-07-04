from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.services import tornado_service
from app.services.proforma import engine, hold

router = APIRouter(prefix="/api/compute", tags=["compute"])


class ComputeRequest(BaseModel):
    values: dict[str, Any]


class TornadoRequest(BaseModel):
    values: dict[str, Any]
    metric: str = "leveredIrr"


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


@router.post("")
def compute(payload: ComputeRequest, detail: bool = False):
    try:
        result = engine.compute(payload.values)
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
