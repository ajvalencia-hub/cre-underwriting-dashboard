"""County-level population and median household income from the Census
Bureau's American Community Survey (5-year estimates). Requires a free key:
https://api.census.gov/data/key_signup.html
"""

import httpx

from app.config import CENSUS_API_KEY

ACS_YEAR = "2022"
ACS_URL = f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5"
_TIMEOUT = 10.0


def get_demographics(state_fips: str | None, county_fips: str | None) -> dict:
    if not CENSUS_API_KEY:
        return {
            "dataSource": "unavailable",
            "note": "Set CENSUS_API_KEY in backend/.env (free signup: "
            "https://api.census.gov/data/key_signup.html).",
        }
    if not state_fips or not county_fips:
        return {"dataSource": "unavailable", "note": "No county resolved for this market."}

    try:
        resp = httpx.get(
            ACS_URL,
            params={
                "get": "NAME,B01003_001E,B19013_001E",
                "for": f"county:{county_fips}",
                "in": f"state:{state_fips}",
                "key": CENSUS_API_KEY,
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        rows = resp.json()
        _name, population, median_income, *_rest = rows[1]
        return {
            "dataSource": "census_acs",
            "acsYear": ACS_YEAR,
            "population": int(population),
            "medianHouseholdIncome": float(median_income),
        }
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
        return {"dataSource": "unavailable", "note": f"Census ACS lookup failed: {exc}"}
