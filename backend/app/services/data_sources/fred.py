"""National mortgage rate / treasury yield context from FRED (St. Louis Fed).
Not market-specific — same for every query — but useful context for the
financing environment. Requires a free key:
https://fred.stlouisfed.org/docs/api/api_key.html
"""

import httpx

from app.config import FRED_API_KEY

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
_TIMEOUT = 10.0


def _latest_observation(series_id: str) -> tuple[float, str] | None:
    resp = httpx.get(
        FRED_URL,
        params={
            "series_id": series_id,
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 1,
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    obs = resp.json().get("observations", [])
    if not obs or obs[0]["value"] == ".":
        return None
    return float(obs[0]["value"]), obs[0]["date"]


_RATE_SERIES = {
    "sofr": "SOFR",
    "treasury5yrPct": "DGS5",
    "treasury10yrPct": "DGS10",
    "mortgage30yrPct": "MORTGAGE30US",
}
_CACHE_MAX_AGE_SECONDS = 24 * 3600


def _cache_path():
    from app.config import STORAGE_ROOT

    cache_dir = STORAGE_ROOT / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "market_rates.json"


def get_market_rates(use_cache: bool = True) -> dict:
    """Current SOFR + 5/10-yr Treasury + 30-yr mortgage from FRED, with a 24h
    on-disk cache. Every rate is a decimal fraction with its own as-of date;
    missing key or a failed source degrades to nulls, never an error."""
    import json
    import time

    path = _cache_path()
    if use_cache and path.exists():
        try:
            cached = json.loads(path.read_text())
            if time.time() - cached.get("fetchedAt", 0) < _CACHE_MAX_AGE_SECONDS:
                return cached["data"]
        except (json.JSONDecodeError, KeyError, OSError):
            pass  # unreadable cache — refetch

    if not FRED_API_KEY:
        return {
            "dataSource": "unavailable",
            "rates": {key: None for key in _RATE_SERIES},
            "note": "Set FRED_API_KEY in backend/.env (free signup: "
            "https://fred.stlouisfed.org/docs/api/api_key.html).",
        }

    rates: dict = {}
    as_of: dict = {}
    failures: list[str] = []
    for key, series in _RATE_SERIES.items():
        try:
            observation = _latest_observation(series)
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            observation = None
            failures.append(f"{series}: {exc}")
        if observation:
            rates[key] = observation[0] / 100
            as_of[key] = observation[1]
        else:
            rates[key] = None

    data = {
        "dataSource": "fred" if any(v is not None for v in rates.values()) else "unavailable",
        "rates": rates,
        "asOf": as_of,
    }
    if failures:
        data["note"] = "; ".join(failures)

    if data["dataSource"] == "fred":
        try:
            path.write_text(json.dumps({"fetchedAt": time.time(), "data": data}))
        except OSError:
            pass  # cache write is best-effort
    return data


def get_macro_rates() -> dict:
    if not FRED_API_KEY:
        return {
            "dataSource": "unavailable",
            "note": "Set FRED_API_KEY in backend/.env (free signup: "
            "https://fred.stlouisfed.org/docs/api/api_key.html).",
        }
    try:
        mortgage = _latest_observation("MORTGAGE30US")
        treasury = _latest_observation("DGS10")
        if mortgage is None and treasury is None:
            return {"dataSource": "unavailable", "note": "FRED returned no recent observations."}
        result: dict = {"dataSource": "fred"}
        if mortgage:
            result["mortgageRate30yrPct"] = mortgage[0] / 100
            result["mortgageRateAsOf"] = mortgage[1]
        if treasury:
            result["treasuryYield10yrPct"] = treasury[0] / 100
            result["treasuryYieldAsOf"] = treasury[1]
        return result
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return {"dataSource": "unavailable", "note": f"FRED lookup failed: {exc}"}
