from fastapi import APIRouter

from app.services.data_sources import fred

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/rates")
def market_rates():
    return fred.get_market_rates()
