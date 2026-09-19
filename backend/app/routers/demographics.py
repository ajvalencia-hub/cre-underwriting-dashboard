from fastapi import APIRouter, Depends, HTTPException

from app.services import demographics, rate_limit

router = APIRouter(prefix="/api/demographics", tags=["demographics"])


@router.get("", dependencies=[Depends(rate_limit.limited("demographics"))])
def get_demographics(market: str = "", submarket: str = "", address: str = ""):
    if not (market.strip() or address.strip()):
        raise HTTPException(400, "market or address is required")
    return demographics.get_demographic_trends(market, submarket, address)
