"""Metro-level home price appreciation from FHFA's House Price Index
(All-Transactions, metro). Free, no key — a static CSV published quarterly:
https://www.fhfa.gov/data/hpi/datasets

The file has no header row; columns are:
metro_name, cbsa_code, year, quarter, index_nsa, standard_deviation
"""

import csv
import io

import httpx

FHFA_URL = "https://www.fhfa.gov/hpi/download/quarterly_datasets/hpi_at_metro.csv"
_TIMEOUT = 15.0
_cache: dict = {"rows": None}


def _load_rows() -> list[list[str]]:
    if _cache["rows"] is None:
        resp = httpx.get(FHFA_URL, timeout=_TIMEOUT)
        resp.raise_for_status()
        _cache["rows"] = list(csv.reader(io.StringIO(resp.text)))
    return _cache["rows"]


def get_home_price_appreciation(cbsa_code: str | None) -> dict:
    if not cbsa_code:
        return {"dataSource": "unavailable", "note": "No metro (CBSA) resolved for this market."}

    try:
        rows = _load_rows()
    except httpx.HTTPError as exc:
        return {"dataSource": "unavailable", "note": f"FHFA HPI download failed: {exc}"}

    metro_rows = [r for r in rows if len(r) >= 5 and r[1] == str(cbsa_code)]
    if len(metro_rows) < 5:
        return {
            "dataSource": "unavailable",
            "note": f"No FHFA HPI series found for CBSA {cbsa_code}.",
        }

    metro_rows.sort(key=lambda r: (int(r[2]), int(r[3])))
    valid = [r for r in metro_rows if r[4] not in ("-", "")]
    if len(valid) < 5:
        return {"dataSource": "unavailable", "note": "Insufficient FHFA HPI history for this metro."}

    latest = valid[-1]
    year_ago = valid[-5]  # same quarter, prior year
    latest_index = float(latest[4])
    year_ago_index = float(year_ago[4])

    return {
        "dataSource": "fhfa",
        "metroName": latest[0],
        "hpiYoYAppreciation": round(latest_index / year_ago_index - 1, 4),
        "asOf": f"{latest[2]} Q{latest[3]}",
    }
