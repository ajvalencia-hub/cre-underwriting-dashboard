from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.services.proforma import engine

router = APIRouter(prefix="/api/compute", tags=["compute"])


class ComputeRequest(BaseModel):
    values: dict[str, Any]


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
