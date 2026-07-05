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
                # population, median household income, median gross rent
                "get": "NAME,B01003_001E,B19013_001E,B25064_001E",
                "for": f"county:{county_fips}",
                "in": f"state:{state_fips}",
                "key": CENSUS_API_KEY,
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        rows = resp.json()
        _name, population, median_income, median_gross_rent, *_rest = rows[1]
        return {
            "dataSource": "census_acs",
            "acsYear": ACS_YEAR,
            "population": int(population),
            "medianHouseholdIncome": float(median_income),
            "medianGrossRent": float(median_gross_rent),
        }
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
        return {"dataSource": "unavailable", "note": f"Census ACS lookup failed: {exc}"}


def get_population_trend(state_fips: str | None, county_fips: str | None) -> dict:
    """Population + median household income across the last 5 ACS 5-year
    vintages (one request per year; failed vintages are skipped)."""
    if not CENSUS_API_KEY:
        return {
            "dataSource": "unavailable",
            "note": "Set CENSUS_API_KEY in backend/.env (free signup: "
            "https://api.census.gov/data/key_signup.html).",
        }
    if not state_fips or not county_fips:
        return {"dataSource": "unavailable", "note": "No county resolved for this market."}

    population: list[dict] = []
    income: list[dict] = []
    last_year = int(ACS_YEAR)
    for year in range(last_year - 4, last_year + 1):
        try:
            resp = httpx.get(
                f"https://api.census.gov/data/{year}/acs/acs5",
                params={
                    "get": "B01003_001E,B19013_001E",
                    "for": f"county:{county_fips}",
                    "in": f"state:{state_fips}",
                    "key": CENSUS_API_KEY,
                },
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            pop, med_income, *_rest = resp.json()[1]
            population.append({"period": str(year), "value": int(pop)})
            income.append({"period": str(year), "value": float(med_income)})
        except (httpx.HTTPError, ValueError, KeyError, IndexError):
            continue  # a missing vintage shouldn't kill the trend
    if len(population) < 2:
        return {"dataSource": "unavailable", "note": "Fewer than 2 ACS vintages available."}
    return {
        "dataSource": "census_acs",
        "population": population,
        "medianHouseholdIncome": income,
    }
