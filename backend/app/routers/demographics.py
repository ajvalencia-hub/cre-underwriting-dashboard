from fastapi import APIRouter, HTTPException

from app.services import demographics

router = APIRouter(prefix="/api/demographics", tags=["demographics"])


@router.get("")
def get_demographics(market: str = "", submarket: str = "", address: str = ""):
    if not (market.strip() or address.strip()):
        raise HTTPException(400, "market or address is required")
    return demographics.get_demographic_trends(market, submarket, address)
