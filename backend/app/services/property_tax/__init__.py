"""County property-tax adapters (H4).

Adapter contract — a module exposing:

    COUNTY: str                       # machine name, e.g. "miami_dade"
    JURISDICTION: str                 # display name, e.g. "Miami-Dade County, FL"
    def lookup(query: str) -> dict    # address or folio/parcel id

lookup() returns (nulls where unknown, never raises):

    {
        "dataSource": COUNTY | "unavailable",
        "folio": str | None,
        "address": str | None,
        "assessedValue": float | None,
        "taxableValue": float | None,
        "millageRate": float | None,   # decimal, e.g. 0.0197 = 19.7 mills
        "currentTaxes": float | None,
        "jurisdiction": str,
        "asOf": str | None,            # tax roll year or date
        "note": str | None,            # human-readable failure/context note
    }

Adding a county: drop a module implementing the contract next to
miami_dade.py, add it to ADAPTERS, and (if its API needs a key) follow the
config.py optional-key pattern. Results should be wrapped in
data_sources.source_cache.cached_fetch (24h), and every network failure must
degrade to dataSource="unavailable" with a note — never an exception.
"""

from app.services.property_tax import miami_dade

ADAPTERS = {
    miami_dade.COUNTY: miami_dade,
}


def lookup(query: str, county: str | None = None) -> dict:
    """Route to the named adapter, or try each registered adapter until one
    finds the parcel."""
    if county:
        adapter = ADAPTERS.get(county)
        if adapter is None:
            return {
                "dataSource": "unavailable",
                "jurisdiction": county,
                "note": f"No adapter for county '{county}'. Available: {', '.join(ADAPTERS)}.",
            }
        return adapter.lookup(query)

    last = None
    for adapter in ADAPTERS.values():
        result = adapter.lookup(query)
        if result.get("dataSource") != "unavailable":
            return result
        last = result
    return last or {
        "dataSource": "unavailable",
        "jurisdiction": "",
        "note": "No property-tax adapters are registered.",
    }
