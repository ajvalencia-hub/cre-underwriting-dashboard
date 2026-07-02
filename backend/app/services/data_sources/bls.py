"""County-level unemployment rate from BLS LAUS (Local Area Unemployment
Statistics). Works unauthenticated at low request volume; set BLS_API_KEY
for a higher rate limit: https://data.bls.gov/registrationEngine/
"""

import httpx

from app.config import BLS_API_KEY

BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
_TIMEOUT = 10.0


def get_unemployment_rate(state_fips: str | None, county_fips: str | None) -> dict:
    if not state_fips or not county_fips:
        return {"dataSource": "unavailable", "note": "No county resolved for this market."}

    series_id = f"LAUCN{state_fips}{county_fips}0000000003"
    payload: dict = {"seriesid": [series_id], "latest": "true"}
    if BLS_API_KEY:
        payload["registrationkey"] = BLS_API_KEY

    try:
        resp = httpx.post(BLS_URL, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        body = resp.json()
        series = body.get("Results", {}).get("series", [])
        if not series or not series[0].get("data"):
            return {
                "dataSource": "unavailable",
                "note": f"BLS returned no data for series {series_id}.",
            }
        point = series[0]["data"][0]
        return {
            "dataSource": "bls",
            "unemploymentRatePct": float(point["value"]) / 100,
            "asOf": f"{point['periodName']} {point['year']}",
        }
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return {"dataSource": "unavailable", "note": f"BLS lookup failed: {exc}"}
