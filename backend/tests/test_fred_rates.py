"""F3: FRED market-rates client — mocked httpx (success, timeout), missing
key, and 24h on-disk cache behavior."""

import json

import httpx
import pytest

from app.services.data_sources import fred


class _StubResponse:
    def __init__(self, value: str = "4.35", date: str = "2026-07-01"):
        self._value = value
        self._date = date

    def raise_for_status(self):
        pass

    def json(self):
        return {"observations": [{"value": self._value, "date": self._date}]}


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(fred, "_cache_path", lambda: tmp_path / "market_rates.json")
    return tmp_path / "market_rates.json"


def test_missing_key_degrades_to_nulls(isolated_cache, monkeypatch):
    monkeypatch.setattr(fred, "FRED_API_KEY", "")
    result = fred.get_market_rates(use_cache=False)
    assert result["dataSource"] == "unavailable"
    assert set(result["rates"]) == {"sofr", "treasury5yrPct", "treasury10yrPct", "mortgage30yrPct"}
    assert all(v is None for v in result["rates"].values())
    assert "FRED_API_KEY" in result["note"]
    assert not isolated_cache.exists()  # nothing cached for the unavailable state


def test_success_fetches_all_series_and_writes_cache(isolated_cache, monkeypatch):
    monkeypatch.setattr(fred, "FRED_API_KEY", "test-key")
    requested: list[str] = []

    def fake_get(url, params=None, timeout=None):
        requested.append(params["series_id"])
        return _StubResponse("4.35")

    monkeypatch.setattr(fred.httpx, "get", fake_get)
    result = fred.get_market_rates(use_cache=False)
    assert result["dataSource"] == "fred"
    assert result["rates"]["sofr"] == pytest.approx(0.0435)
    assert result["asOf"]["treasury10yrPct"] == "2026-07-01"
    assert set(requested) == {"SOFR", "DGS5", "DGS10", "MORTGAGE30US"}
    assert isolated_cache.exists()


def test_cache_hit_avoids_network(isolated_cache, monkeypatch):
    monkeypatch.setattr(fred, "FRED_API_KEY", "test-key")
    monkeypatch.setattr(fred.httpx, "get", lambda *a, **k: _StubResponse("5.00"))
    first = fred.get_market_rates(use_cache=False)  # populates the cache

    def explode(*args, **kwargs):
        raise AssertionError("network must not be hit on a warm cache")

    monkeypatch.setattr(fred.httpx, "get", explode)
    cached = fred.get_market_rates(use_cache=True)
    assert cached == first


def test_stale_cache_refetches(isolated_cache, monkeypatch):
    monkeypatch.setattr(fred, "FRED_API_KEY", "test-key")
    isolated_cache.write_text(
        json.dumps({"fetchedAt": 0, "data": {"dataSource": "fred", "rates": {"sofr": 0.01}}})
    )
    monkeypatch.setattr(fred.httpx, "get", lambda *a, **k: _StubResponse("4.00"))
    result = fred.get_market_rates(use_cache=True)
    assert result["rates"]["sofr"] == pytest.approx(0.04)


def test_timeout_degrades_gracefully_per_source(isolated_cache, monkeypatch):
    monkeypatch.setattr(fred, "FRED_API_KEY", "test-key")

    def timeout_get(url, params=None, timeout=None):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(fred.httpx, "get", timeout_get)
    result = fred.get_market_rates(use_cache=False)
    assert result["dataSource"] == "unavailable"
    assert all(v is None for v in result["rates"].values())
    assert "timed out" in result["note"]


def test_partial_failure_keeps_working_series(isolated_cache, monkeypatch):
    monkeypatch.setattr(fred, "FRED_API_KEY", "test-key")

    def flaky_get(url, params=None, timeout=None):
        if params["series_id"] == "SOFR":
            raise httpx.TimeoutException("SOFR down")
        return _StubResponse("4.10")

    monkeypatch.setattr(fred.httpx, "get", flaky_get)
    result = fred.get_market_rates(use_cache=False)
    assert result["dataSource"] == "fred"
    assert result["rates"]["sofr"] is None
    assert result["rates"]["treasury10yrPct"] == pytest.approx(0.041)
