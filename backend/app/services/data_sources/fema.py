"""Flood zone at a point from FEMA's National Flood Hazard Layer (NFHL).
Free, no key: https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer
"""

import httpx

FEMA_URL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
_TIMEOUT = 15.0

_ZONE_DESCRIPTIONS = {
    "X": "Minimal flood hazard",
    "A": "1% annual chance flood (high risk), no base flood elevation determined",
    "AE": "1% annual chance flood (high risk), base flood elevation determined",
    "AH": "1% annual chance shallow flooding, average depths 1-3 ft",
    "AO": "1% annual chance sheet flow flooding, average depths 1-3 ft",
    "V": "Coastal high hazard area, no base flood elevation determined",
    "VE": "Coastal high hazard area, base flood elevation determined",
    "D": "Undetermined flood hazard",
}


def get_flood_zone(lat: float | None, lon: float | None) -> dict:
    if lat is None or lon is None:
        return {"dataSource": "unavailable", "note": "No coordinates resolved for this market."}

    try:
        resp = httpx.get(
            FEMA_URL,
            params={
                "geometry": f"{lon},{lat}",
                "geometryType": "esriGeometryPoint",
                "inSR": 4326,
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": "FLD_ZONE,ZONE_SUBTY",
                "returnGeometry": "false",
                "f": "json",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        features = resp.json().get("features", [])
        if not features:
            return {
                "dataSource": "fema",
                "floodZone": "X",
                "description": "No mapped flood hazard at this point (likely minimal hazard).",
            }
        attrs = features[0]["attributes"]
        zone = attrs.get("FLD_ZONE", "")
        return {
            "dataSource": "fema",
            "floodZone": zone,
            "zoneSubtype": attrs.get("ZONE_SUBTY"),
            "description": _ZONE_DESCRIPTIONS.get(zone, "See FEMA flood zone documentation."),
        }
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return {"dataSource": "unavailable", "note": f"FEMA flood zone lookup failed: {exc}"}
