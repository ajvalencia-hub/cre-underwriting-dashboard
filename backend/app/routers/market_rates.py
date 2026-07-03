from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.services import benchmarks
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
def market_benchmarks(payload: BenchmarkRequest):
    return benchmarks.build_benchmarks(
        payload.address, payload.market, payload.submarket, payload.assetClass, payload.subject
    )
