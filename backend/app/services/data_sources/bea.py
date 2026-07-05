"""Regional per-capita personal income and its YoY growth from the BEA
Regional dataset (CAINC1, county-level). Requires a free key:
https://apps.bea.gov/API/signup/
"""

import httpx

from app.config import BEA_API_KEY

BEA_URL = "https://apps.bea.gov/api/data/"
_TIMEOUT = 15.0


def get_income_growth(state_fips: str | None, county_fips: str | None) -> dict:
    if not BEA_API_KEY:
        return {
            "dataSource": "unavailable",
            "note": "Set BEA_API_KEY in backend/.env (free signup: "
            "https://apps.bea.gov/API/signup/).",
        }
    if not state_fips or not county_fips:
        return {"dataSource": "unavailable", "note": "No county resolved for this market."}

    geo_fips = f"{state_fips}{county_fips}"
    try:
        resp = httpx.get(
            BEA_URL,
            params={
                "UserID": BEA_API_KEY,
                "method": "GetData",
                "datasetname": "Regional",
                "TableName": "CAINC1",
                "LineCode": "3",  # Per capita personal income
                "GeoFips": geo_fips,
                "Year": "LAST5",
                "ResultFormat": "JSON",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        results = resp.json()["BEAAPI"]["Results"]
        if "Error" in results:
            return {
                "dataSource": "unavailable",
                "note": f"BEA error: {results['Error']['APIErrorDescription']}",
            }
        data = sorted(
            (d for d in results["Data"] if d["DataValue"] not in ("(NA)", "(D)")),
            key=lambda d: d["TimePeriod"],
        )
        if len(data) < 2:
            return {"dataSource": "unavailable", "note": "BEA returned insufficient data points."}
        latest, prior = data[-1], data[-2]
        latest_val = float(latest["DataValue"].replace(",", ""))
        prior_val = float(prior["DataValue"].replace(",", ""))
        return {
            "dataSource": "bea",
            "perCapitaPersonalIncome": latest_val,
            "personalIncomeGrowthYoY": round(latest_val / prior_val - 1, 4),
            "asOf": latest["TimePeriod"],
        }
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
        return {"dataSource": "unavailable", "note": f"BEA lookup failed: {exc}"}


def get_income_series(state_fips: str | None, county_fips: str | None) -> dict:
    """Per-capita personal income, last 10 years, ascending."""
    if not BEA_API_KEY:
        return {
            "dataSource": "unavailable",
            "note": "Set BEA_API_KEY in backend/.env (free signup: "
            "https://apps.bea.gov/API/signup/).",
        }
    if not state_fips or not county_fips:
        return {"dataSource": "unavailable", "note": "No county resolved for this market."}

    try:
        resp = httpx.get(
            BEA_URL,
            params={
                "UserID": BEA_API_KEY,
                "method": "GetData",
                "datasetname": "Regional",
                "TableName": "CAINC1",
                "LineCode": "3",
                "GeoFips": f"{state_fips}{county_fips}",
                "Year": "LAST10",
                "ResultFormat": "JSON",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        results = resp.json()["BEAAPI"]["Results"]
        if "Error" in results:
            return {
                "dataSource": "unavailable",
                "note": f"BEA error: {results['Error']['APIErrorDescription']}",
            }
        data = sorted(
            (d for d in results["Data"] if d["DataValue"] not in ("(NA)", "(D)")),
            key=lambda d: d["TimePeriod"],
        )
        if len(data) < 2:
            return {"dataSource": "unavailable", "note": "BEA returned insufficient data points."}
        return {
            "dataSource": "bea",
            "perCapitaPersonalIncome": [
                {"period": d["TimePeriod"], "value": float(d["DataValue"].replace(",", ""))}
                for d in data
            ],
        }
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
        return {"dataSource": "unavailable", "note": f"BEA series lookup failed: {exc}"}
