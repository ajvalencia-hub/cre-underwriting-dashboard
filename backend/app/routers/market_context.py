from fastapi import APIRouter, Depends, HTTPException

from app.schemas import MarketContextResponse
from app.services import market_context, rate_limit

router = APIRouter(prefix="/api/market-context", tags=["market-context"])


@router.get(
    "",
    response_model=MarketContextResponse,
    dependencies=[Depends(rate_limit.limited("market_context"))],
)
def get_market_context(market: str, submarket: str = "", asset_class: str = ""):
    if not market.strip():
        raise HTTPException(400, "market is required")
    return market_context.get_market_context(market, submarket, asset_class)
