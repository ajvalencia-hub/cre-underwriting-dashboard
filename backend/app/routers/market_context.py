from fastapi import APIRouter, HTTPException

from app.schemas import MarketContextResponse
from app.services import market_context

router = APIRouter(prefix="/api/market-context", tags=["market-context"])


@router.get("", response_model=MarketContextResponse)
def get_market_context(market: str, submarket: str = "", asset_class: str = ""):
    if not market.strip():
        raise HTTPException(400, "market is required")
    return market_context.get_market_context(market, submarket, asset_class)
