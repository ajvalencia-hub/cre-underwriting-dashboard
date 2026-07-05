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


def get_employment_trend(state_fips: str | None, county_fips: str | None) -> dict:
    """County employment level YoY from the LAUS employment series (datatype
    05) — the robust way to read a local employment trend without QCEW's
    fragile series-id construction."""
    if not state_fips or not county_fips:
        return {"dataSource": "unavailable", "note": "No county resolved for this market."}

    from datetime import date

    series_id = f"LAUCN{state_fips}{county_fips}0000000005"
    payload: dict = {
        "seriesid": [series_id],
        "startyear": str(date.today().year - 2),
        "endyear": str(date.today().year),
    }
    if BLS_API_KEY:
        payload["registrationkey"] = BLS_API_KEY

    try:
        resp = httpx.post(BLS_URL, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        series = resp.json().get("Results", {}).get("series", [])
        points = series[0].get("data", []) if series else []
        if not points:
            return {"dataSource": "unavailable", "note": f"BLS returned no data for {series_id}."}
        latest = points[0]  # BLS returns newest first
        prior = next(
            (p for p in points if p["period"] == latest["period"] and int(p["year"]) == int(latest["year"]) - 1),
            None,
        )
        if prior is None:
            return {"dataSource": "unavailable", "note": "No prior-year employment point to compare."}
        latest_value, prior_value = float(latest["value"]), float(prior["value"])
        if prior_value <= 0:
            return {"dataSource": "unavailable", "note": "Prior-year employment level was zero."}
        return {
            "dataSource": "bls",
            "employmentYoYGrowth": round(latest_value / prior_value - 1, 4),
            "employmentLevel": latest_value,
            "asOf": f"{latest['periodName']} {latest['year']}",
        }
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
        return {"dataSource": "unavailable", "note": f"BLS employment lookup failed: {exc}"}


def get_employment_series(state_fips: str | None, county_fips: str | None) -> dict:
    """Monthly county employment level and unemployment rate for the last ~3
    years (both LAUS series in one request), ascending."""
    if not state_fips or not county_fips:
        return {"dataSource": "unavailable", "note": "No county resolved for this market."}

    from datetime import date

    employment_id = f"LAUCN{state_fips}{county_fips}0000000005"
    unemployment_id = f"LAUCN{state_fips}{county_fips}0000000003"
    payload: dict = {
        "seriesid": [employment_id, unemployment_id],
        "startyear": str(date.today().year - 3),
        "endyear": str(date.today().year),
    }
    if BLS_API_KEY:
        payload["registrationkey"] = BLS_API_KEY

    def _points(series_data: list, scale: float) -> list[dict]:
        points = [
            {
                "period": f"{p['year']}-{p['period'][1:]}",  # "M03" -> "2025-03"
                "value": float(p["value"]) * scale,
            }
            for p in series_data
            if p.get("period", "").startswith("M") and p["period"] != "M13"
        ]
        return sorted(points, key=lambda p: p["period"])

    try:
        resp = httpx.post(BLS_URL, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        series = {
            s["seriesID"]: s.get("data", [])
            for s in resp.json().get("Results", {}).get("series", [])
        }
        employment = _points(series.get(employment_id, []), 1.0)
        unemployment = _points(series.get(unemployment_id, []), 0.01)
        if not employment and not unemployment:
            return {"dataSource": "unavailable", "note": "BLS returned no series data."}
        return {
            "dataSource": "bls",
            "employmentLevel": employment,
            "unemploymentRatePct": unemployment,
        }
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
        return {"dataSource": "unavailable", "note": f"BLS series lookup failed: {exc}"}
