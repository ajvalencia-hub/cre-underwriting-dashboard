from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import benchmarks, comps
from app.services.data_sources import fred

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/rates")
def market_rates():
    return fred.get_market_rates()


class BenchmarkRequest(BaseModel):
    address: str = ""
    market: str = ""
    submarket: str = ""
    assetClass: str = ""
    subject: dict[str, Any] = {}


@router.post("/benchmarks")
def market_benchmarks(payload: BenchmarkRequest, db: Session = Depends(get_db)):
    result = benchmarks.build_benchmarks(
        payload.address, payload.market, payload.submarket, payload.assetClass, payload.subject
    )
    # H5: comps-DB flags ride alongside the public-source flags.
    result["flags"].extend(
        comps.benchmark_flags(db, payload.market, payload.assetClass, payload.subject)
    )
    return result
