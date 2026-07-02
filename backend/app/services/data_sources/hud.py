"""Fair Market Rents from HUD USER. Requires a free account + bearer token:
https://www.huduser.gov/hudapi/public/register?comingfrom=1

NOTE: HUD's entity-id convention for county-level FMR queries is the 5-digit
state+county FIPS code plus a "99999" suffix (10 digits total). If HUD has
changed this convention since, this surfaces as an "unavailable" result with
the raw error rather than fabricated numbers — check
https://www.huduser.gov/portal/dataset/fmr-api.html if it stops matching.
"""

import httpx

from app.config import HUD_API_TOKEN

HUD_URL = "https://www.huduser.gov/hudapi/public/fmr/data/"
_TIMEOUT = 10.0


def get_fair_market_rents(state_fips: str | None, county_fips: str | None) -> dict:
    if not HUD_API_TOKEN:
        return {
            "dataSource": "unavailable",
            "note": "Set HUD_API_TOKEN in backend/.env (free signup: "
            "https://www.huduser.gov/hudapi/public/register?comingfrom=1).",
        }
    if not state_fips or not county_fips:
        return {"dataSource": "unavailable", "note": "No county resolved for this market."}

    entity_id = f"{state_fips}{county_fips}99999"
    try:
        resp = httpx.get(
            f"{HUD_URL}{entity_id}",
            headers={"Authorization": f"Bearer {HUD_API_TOKEN}"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        basic = data.get("basicdata")
        if isinstance(basic, list):
            basic = basic[0] if basic else {}
        if not basic:
            return {"dataSource": "unavailable", "note": "HUD returned no FMR data for this county."}
        return {
            "dataSource": "hud",
            "fmrStudio": basic.get("Efficiency"),
            "fmr1BR": basic.get("One-Bedroom"),
            "fmr2BR": basic.get("Two-Bedroom"),
            "fmr3BR": basic.get("Three-Bedroom"),
            "year": data.get("year"),
        }
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return {"dataSource": "unavailable", "note": f"HUD FMR lookup failed: {exc}"}
