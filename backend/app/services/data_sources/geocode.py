"""Resolve a free-text market/submarket (and optionally a street address) to
real geography identifiers — lat/lon, county FIPS, state FIPS, and CBSA (metro)
code — that the other data_sources modules key their queries on.

Two free, no-key services, chained:
  1. Nominatim (OpenStreetMap) — text -> lat/lon. Usage policy requires an
     identifying User-Agent and caps at ~1 request/sec; fine for this app's
     interactive, debounced usage pattern.
  2. Census Bureau coordinate-based geography lookup — lat/lon -> county FIPS,
     state FIPS, CBSA code/name. No key required.
"""

import httpx

from app.config import GEOCODE_USER_AGENT

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
CENSUS_GEOGRAPHIES_URL = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"

_TIMEOUT = 10.0


def _geocode_text(query: str) -> tuple[float, float] | None:
    resp = httpx.get(
        NOMINATIM_URL,
        params={"q": query, "format": "json", "limit": 1},
        headers={"User-Agent": GEOCODE_USER_AGENT},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    results = resp.json()
    if not results:
        return None
    return float(results[0]["lat"]), float(results[0]["lon"])


def _lookup_geographies(lat: float, lon: float) -> dict:
    resp = httpx.get(
        CENSUS_GEOGRAPHIES_URL,
        params={
            "x": lon,
            "y": lat,
            "benchmark": "Public_AR_Current",
            "vintage": "Current_Current",
            "layers": "all",
            "format": "json",
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    geos = resp.json()["result"]["geographies"]

    counties = geos.get("Counties") or []
    tracts = geos.get("Census Tracts") or []
    cbsas = (
        geos.get("Metropolitan Statistical Areas")
        or geos.get("Micropolitan Statistical Areas")
        or []
    )

    county = counties[0] if counties else {}
    tract = tracts[0] if tracts else {}
    cbsa = cbsas[0] if cbsas else {}

    return {
        "stateFips": county.get("STATE"),
        "countyFips": county.get("COUNTY"),
        "countyName": county.get("BASENAME"),
        "tractCode": tract.get("TRACT"),
        "cbsaCode": cbsa.get("CBSA"),
        "cbsaName": cbsa.get("BASENAME"),
    }


def geocode(market: str, submarket: str = "", address: str = "") -> dict:
    """Best-effort resolution. Tries the street address first (most precise),
    then falls back to 'submarket, market' as a locality-level query.

    Returns {"resolved": False} if nothing could be geocoded — callers should
    treat that as "no geography-keyed data available for this query" rather
    than an error, since an unrecognized market name is normal user input,
    not a bug.
    """
    query_candidates = [
        q
        for q in (address, f"{submarket}, {market}" if submarket else market)
        if q and q.strip()
    ]

    for query in query_candidates:
        try:
            coords = _geocode_text(query)
        except httpx.HTTPError:
            continue
        if coords is None:
            continue
        lat, lon = coords
        try:
            geos = _lookup_geographies(lat, lon)
        except httpx.HTTPError:
            continue
        return {"resolved": True, "lat": lat, "lon": lon, "query": query, **geos}

    return {"resolved": False}
