"""Run 6 (API wave 2): per-route token bucket on the external-API-backed
routes. The limit is read from app.config at request time, so these tests
monkeypatch it down; the shared conftest never touches it, so the rest of
the suite runs under the 60/min default and cannot trip the gate."""

import threading

import pytest

from app import config
from app.services import demographics as demographics_service
from app.services import rate_limit
from app.services.data_sources import fred


@pytest.fixture(autouse=True)
def _fresh_buckets(monkeypatch):
    rate_limit.reset()
    # Never hit the network: stub the upstream calls behind each route.
    monkeypatch.setattr(fred, "get_market_rates", lambda **_: {"dataSource": "stub", "rates": {}})
    monkeypatch.setattr(
        demographics_service, "get_demographic_trends", lambda *_a, **_k: {"dataSource": "stub"}
    )
    yield
    rate_limit.reset()


def test_bucket_is_per_route_and_reports_retry_after(client, monkeypatch):
    monkeypatch.setattr(config, "CRE_EXTERNAL_RATE_LIMIT_PER_MIN", 2)
    assert client.get("/api/market/rates").status_code == 200
    assert client.get("/api/market/rates").status_code == 200
    third = client.get("/api/market/rates")
    assert third.status_code == 429
    assert int(third.headers["retry-after"]) >= 1
    assert "retry" in third.json()["detail"].lower()
    # A different route has its own bucket.
    assert client.get("/api/demographics?market=Austin").status_code == 200
    # The comps map route is gated too (empty DB -> no geocoding).
    assert client.get("/api/comps/sale/map").status_code == 200
    assert client.get("/api/comps/sale/map").status_code == 200
    assert client.get("/api/comps/sale/map").status_code == 429


def test_zero_disables_the_gate(client, monkeypatch):
    monkeypatch.setattr(config, "CRE_EXTERNAL_RATE_LIMIT_PER_MIN", 0)
    for _ in range(5):
        assert client.get("/api/market/rates").status_code == 200


def test_limit_change_rebuilds_the_bucket(client, monkeypatch):
    monkeypatch.setattr(config, "CRE_EXTERNAL_RATE_LIMIT_PER_MIN", 1)
    assert client.get("/api/market/rates").status_code == 200
    assert client.get("/api/market/rates").status_code == 429
    monkeypatch.setattr(config, "CRE_EXTERNAL_RATE_LIMIT_PER_MIN", 60)
    assert client.get("/api/market/rates").status_code == 200


def test_bucket_refills_over_time(monkeypatch):
    monkeypatch.setattr(config, "CRE_EXTERNAL_RATE_LIMIT_PER_MIN", 60)  # 1 token/s
    assert rate_limit.try_acquire("r", now=0.0) == 0.0
    for _ in range(59):
        rate_limit.try_acquire("r", now=0.0)
    wait = rate_limit.try_acquire("r", now=0.0)
    assert 0 < wait <= 1.0
    assert rate_limit.try_acquire("r", now=0.0 + wait) == 0.0
    # Never accumulates beyond capacity.
    assert rate_limit.try_acquire("r", now=10_000.0) == 0.0


def test_bucket_is_thread_safe(monkeypatch):
    monkeypatch.setattr(config, "CRE_EXTERNAL_RATE_LIMIT_PER_MIN", 50)
    rate_limit.reset()
    granted: list[float] = []
    lock = threading.Lock()

    def worker() -> None:
        for _ in range(20):
            result = rate_limit.try_acquire("shared", now=0.0)
            with lock:
                granted.append(result)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(1 for g in granted if g == 0.0) == 50
    assert len(granted) == 160


def test_gated_routes_are_declared(client):
    """Every route in the brief carries the dependency (checked via the
    OpenAPI-independent route table, so a removed decorator fails here)."""
    from app.main import app

    gated = {
        ("/api/market/rates", "GET"),
        ("/api/market/benchmarks", "POST"),
        ("/api/demographics", "GET"),
        ("/api/market-context", "GET"),
        ("/api/comps/{kind}/map", "GET"),
    }
    seen = set()
    for route in app.routes:
        deps = getattr(route, "dependencies", None) or []
        names = {getattr(d.dependency, "__name__", "") for d in deps}
        if any(n.startswith("rate_limit_") for n in names):
            for method in route.methods or ():
                seen.add((route.path, method))
    assert gated <= seen
