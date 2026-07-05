"""Demographics trend panel (H6): time-series composition over the existing
benchmark data sources. Same resilience contract as benchmarks.py — every
source degrades to dataSource="unavailable" + note, one failure never blocks
the rest, and everything rides the 24h source cache. Context only: nothing
here touches deal inputs.

Series shape everywhere: [{"period": str, "value": float}], ascending.
"""

from app.services.data_sources import bea, bls, census_acs, fhfa, geocode
from app.services.data_sources.source_cache import cached_fetch


def get_demographic_trends(market: str, submarket: str, address: str) -> dict:
    geo_key = f"geo_{address or submarket or market}"
    location = cached_fetch(
        geo_key,
        lambda: {**geocode.geocode(market, submarket, address), "dataSource": "geocode"},
    )
    state_fips = location.get("stateFips")
    county_fips = location.get("countyFips")
    cbsa_code = location.get("cbsaCode")
    county_key = f"{state_fips}{county_fips}"

    def load(name: str, fetch) -> dict:
        try:
            return cached_fetch(name, fetch)
        except Exception as exc:  # noqa: BLE001 - a source bug must not kill the panel
            return {"dataSource": "unavailable", "note": f"{name} failed unexpectedly: {exc}"}

    return {
        "location": location,
        "population": load(
            f"acs_trend_{county_key}",
            lambda: census_acs.get_population_trend(state_fips, county_fips),
        ),
        "employment": load(
            f"bls_series_{county_key}",
            lambda: bls.get_employment_series(state_fips, county_fips),
        ),
        "homePrices": load(
            f"fhfa_series_{cbsa_code}", lambda: fhfa.get_hpi_series(cbsa_code)
        ),
        "income": load(
            f"bea_series_{county_key}",
            lambda: bea.get_income_series(state_fips, county_fips),
        ),
    }
