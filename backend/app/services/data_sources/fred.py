"""National mortgage rate / treasury yield context from FRED (St. Louis Fed).
Not market-specific — same for every query — but useful context for the
financing environment. Requires a free key:
https://fred.stlouisfed.org/docs/api/api_key.html
"""

import httpx

from app.config import FRED_API_KEY

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
_TIMEOUT = 10.0


def _latest_observation(series_id: str) -> tuple[float, str] | None:
    resp = httpx.get(
        FRED_URL,
        params={
            "series_id": series_id,
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 1,
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    obs = resp.json().get("observations", [])
    if not obs or obs[0]["value"] == ".":
        return None
    return float(obs[0]["value"]), obs[0]["date"]


def get_macro_rates() -> dict:
    if not FRED_API_KEY:
        return {
            "dataSource": "unavailable",
            "note": "Set FRED_API_KEY in backend/.env (free signup: "
            "https://fred.stlouisfed.org/docs/api/api_key.html).",
        }
    try:
        mortgage = _latest_observation("MORTGAGE30US")
        treasury = _latest_observation("DGS10")
        if mortgage is None and treasury is None:
            return {"dataSource": "unavailable", "note": "FRED returned no recent observations."}
        result: dict = {"dataSource": "fred"}
        if mortgage:
            result["mortgageRate30yrPct"] = mortgage[0] / 100
            result["mortgageRateAsOf"] = mortgage[1]
        if treasury:
            result["treasuryYield10yrPct"] = treasury[0] / 100
            result["treasuryYieldAsOf"] = treasury[1]
        return result
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return {"dataSource": "unavailable", "note": f"FRED lookup failed: {exc}"}
