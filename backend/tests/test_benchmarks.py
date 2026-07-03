"""F6: address-driven benchmarks — percentile math, per-source mocked
clients, cache behavior, and partial-failure isolation."""

import httpx
import pytest

from app.services import benchmarks
from app.services.data_sources import bls, census_acs, fema, source_cache


# ------------------------------------------------------------ percentile

def test_rent_percentile_hits_the_anchor_quantiles():
    # FMR = 40th percentile by HUD definition, ACS median = 50th.
    assert benchmarks.estimate_rent_percentile(1500, 1350, 1500) == pytest.approx(0.50, abs=1e-6)
    assert benchmarks.estimate_rent_percentile(1350, 1350, 1500) == pytest.approx(0.40, abs=1e-6)


def test_rent_percentile_is_monotonic_and_flags_high_rents():
    p_low = benchmarks.estimate_rent_percentile(1200, 1350, 1500)
    p_mid = benchmarks.estimate_rent_percentile(1600, 1350, 1500)
    p_high = benchmarks.estimate_rent_percentile(2600, 1350, 1500)
    assert p_low < 0.40 < p_mid < p_high
    assert p_high > benchmarks.RENT_PERCENTILE_WARNING


def test_rent_percentile_single_anchor_fallback():
    # Median-only: subject at the median is the 50th percentile.
    assert benchmarks.estimate_rent_percentile(1500, None, 1500) == pytest.approx(0.5, abs=1e-9)
    # Degenerate FMR >= median also falls back to the median anchor.
    assert benchmarks.estimate_rent_percentile(1500, 1600, 1500) == pytest.approx(0.5, abs=1e-9)
    assert benchmarks.estimate_rent_percentile(1500, None, None) is None


# ------------------------------------------------------- mocked sources

class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_acs_returns_median_gross_rent(monkeypatch):
    monkeypatch.setattr(census_acs, "CENSUS_API_KEY", "k")
    monkeypatch.setattr(
        census_acs.httpx, "get",
        lambda *a, **k: _Resp([["NAME", "pop", "inc", "rent", "st", "co"],
                               ["Travis County", "1300000", "85000", "1650", "48", "453"]]),
    )
    result = census_acs.get_demographics("48", "453")
    assert result["medianGrossRent"] == pytest.approx(1650.0)


def test_bls_employment_trend_matches_same_period_prior_year(monkeypatch):
    payload = {
        "Results": {"series": [{"data": [
            {"year": "2026", "period": "M05", "periodName": "May", "value": "515000"},
            {"year": "2026", "period": "M04", "periodName": "April", "value": "512000"},
            {"year": "2025", "period": "M05", "periodName": "May", "value": "500000"},
        ]}]}
    }
    monkeypatch.setattr(bls.httpx, "post", lambda *a, **k: _Resp(payload))
    result = bls.get_employment_trend("48", "453")
    assert result["employmentYoYGrowth"] == pytest.approx(0.03)
    assert result["asOf"] == "May 2026"


def test_bls_employment_trend_timeout_degrades(monkeypatch):
    def boom(*a, **k):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(bls.httpx, "post", boom)
    result = bls.get_employment_trend("48", "453")
    assert result["dataSource"] == "unavailable"
    assert "timed out" in result["note"]


def test_fema_high_risk_zone(monkeypatch):
    monkeypatch.setattr(
        fema.httpx, "get",
        lambda *a, **k: _Resp({"features": [{"attributes": {"FLD_ZONE": "AE", "ZONE_SUBTY": ""}}]}),
    )
    result = fema.get_flood_zone(30.2, -97.7)
    assert result["floodZone"] == "AE"


# ------------------------------------------------------------- caching

def test_cached_fetch_writes_and_hits(tmp_path, monkeypatch):
    monkeypatch.setattr(source_cache, "STORAGE_ROOT", tmp_path)
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return {"dataSource": "test", "value": 42}

    first = source_cache.cached_fetch("case", fetch)
    second = source_cache.cached_fetch("case", fetch)
    assert first == second
    assert calls["n"] == 1  # second call served from disk


def test_cached_fetch_never_caches_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(source_cache, "STORAGE_ROOT", tmp_path)
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return {"dataSource": "unavailable", "note": "down"}

    source_cache.cached_fetch("down", fetch)
    source_cache.cached_fetch("down", fetch)
    assert calls["n"] == 2  # retried, not pinned


# -------------------------------------------------- service integration

@pytest.fixture
def stubbed_sources(monkeypatch):
    monkeypatch.setattr(benchmarks, "cached_fetch", lambda key, fetch, ttl_seconds=0: fetch())
    monkeypatch.setattr(
        benchmarks.geocode, "geocode",
        lambda market, submarket="", address="": {
            "resolved": True, "lat": 30.2, "lon": -97.7,
            "stateFips": "48", "countyFips": "453", "countyName": "Travis",
            "tractCode": "001100", "cbsaCode": "12420", "cbsaName": "Austin",
        },
    )
    monkeypatch.setattr(
        benchmarks.census_acs, "get_demographics",
        lambda s, c: {"dataSource": "census_acs", "acsYear": "2022",
                      "medianGrossRent": 1500.0, "medianHouseholdIncome": 85000.0, "population": 1300000},
    )
    monkeypatch.setattr(
        benchmarks.hud, "get_fair_market_rents",
        lambda s, c: {"dataSource": "hud", "fmrStudio": 1100, "fmr1BR": 1250,
                      "fmr2BR": 1350, "fmr3BR": 1750, "year": "2026"},
    )
    monkeypatch.setattr(
        benchmarks.fhfa, "get_home_price_appreciation",
        lambda cbsa: {"dataSource": "fhfa", "hpiYoYAppreciation": 0.03,
                      "metroName": "Austin", "asOf": "2026 Q1"},
    )
    monkeypatch.setattr(
        benchmarks.bls, "get_employment_trend",
        lambda s, c: {"dataSource": "bls", "employmentYoYGrowth": 0.02, "asOf": "May 2026"},
    )
    monkeypatch.setattr(
        benchmarks.fema, "get_flood_zone",
        lambda lat, lon: {"dataSource": "fema", "floodZone": "AE",
                          "description": "1% annual chance flood"},
    )


def test_build_benchmarks_produces_all_flags(stubbed_sources):
    result = benchmarks.build_benchmarks(
        "701 Congress Ave, Austin, TX", "Austin", "Downtown", "multifamily",
        subject={
            # Mix-weighted FMR = (60x1250 + 40x1350)/100 = 1290; with the ACS
            # median at 1500 the log-normal fit puts 3200 at the ~90th
            # percentile -> warning.
            "avgRentMonthly": 3200,
            "bedroomMix": [{"bedrooms": 1, "count": 60}, {"bedrooms": 2, "count": 40}],
            "rentGrowthPct": 0.08,  # 5pts over the 3% HPA -> warning
            "expenseRatioPct": 0.62,  # outside the band -> caution
        },
    )
    by_metric = {f["metric"]: f for f in result["flags"]}
    assert by_metric["rent_vs_market"]["verdict"] == "warning"
    assert by_metric["rent_growth_vs_hpa"]["verdict"] == "warning"
    assert by_metric["expense_ratio"]["verdict"] == "caution"
    assert by_metric["flood_zone"]["verdict"] == "warning"  # AE zone
    assert by_metric["employment_trend"]["verdict"] == "ok"
    assert result["unavailable"] == []
    # Every flag carries provenance for the UI.
    assert all(f["source"] for f in result["flags"])
    assert "rentGrowthPct" in by_metric["rent_growth_vs_hpa"]["relatedFieldIds"]


def test_one_failed_source_never_blocks_the_rest(stubbed_sources, monkeypatch):
    def explode(s, c):
        raise RuntimeError("HUD exploded")

    monkeypatch.setattr(benchmarks.hud, "get_fair_market_rents", explode)
    result = benchmarks.build_benchmarks(
        "701 Congress Ave", "Austin", "", "multifamily",
        subject={"avgRentMonthly": 1500, "rentGrowthPct": 0.03, "expenseRatioPct": 0.45},
    )
    metrics = {f["metric"] for f in result["flags"]}
    # rent_vs_market still runs on the ACS median alone.
    assert "rent_vs_market" in metrics
    assert "rent_growth_vs_hpa" in metrics
    assert "flood_zone" in metrics
    assert any("HUD exploded" in u["note"] for u in result["unavailable"])


def test_sane_deal_is_all_ok(stubbed_sources, monkeypatch):
    monkeypatch.setattr(
        benchmarks.fema, "get_flood_zone",
        lambda lat, lon: {"dataSource": "fema", "floodZone": "X", "description": "Minimal"},
    )
    result = benchmarks.build_benchmarks(
        "701 Congress Ave", "Austin", "", "multifamily",
        subject={"avgRentMonthly": 1450, "rentGrowthPct": 0.03, "expenseRatioPct": 0.45},
    )
    assert all(f["verdict"] == "ok" for f in result["flags"])
