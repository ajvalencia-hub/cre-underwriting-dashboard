"""H13: hardening — request-id middleware, client-error sink, and the LRU
compute cache's safety rules."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import compute_cache
from app.services.proforma import engine

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def analytic() -> dict:
    return json.loads((FIXTURES / "analytic_acquisition.json").read_text())


@pytest.fixture(autouse=True)
def fresh_cache():
    compute_cache.clear()
    yield
    compute_cache.clear()


def test_request_id_is_assigned_and_echoed():
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.headers.get("X-Request-ID")

    honored = client.get("/api/health", headers={"X-Request-ID": "trace-me-123"})
    assert honored.headers["X-Request-ID"] == "trace-me-123"


def test_client_error_sink_logs_and_bounds(caplog):
    client = TestClient(app)
    huge = "x" * 100_000
    with caplog.at_level("WARNING", logger="app.client"):
        response = client.post(
            "/api/client-errors",
            json={"message": huge, "stack": huge, "url": "http://localhost/deal"},
        )
    assert response.json() == {"logged": True}
    record = next(r for r in caplog.records if "client-error" in r.getMessage())
    assert len(record.getMessage()) < 20_000  # bounded, not the raw 200k


def test_compute_cache_hits_and_deep_copies(analytic, monkeypatch):
    calls = {"n": 0}
    real_compute = engine.compute

    def counting_compute(inputs):
        calls["n"] += 1
        return real_compute(inputs)

    monkeypatch.setattr(compute_cache.engine, "compute", counting_compute)

    first = compute_cache.cached_compute(analytic)
    second = compute_cache.cached_compute(dict(reversed(list(analytic.items()))))
    assert calls["n"] == 1  # key ordering never splits the cache
    assert second["outputs"] == first["outputs"]

    # Mutating a returned result must not poison the cache.
    second["outputs"]["leveredIrr"] = -999
    third = compute_cache.cached_compute(analytic)
    assert third["outputs"]["leveredIrr"] == first["outputs"]["leveredIrr"]

    stats = compute_cache.cache_stats()
    assert stats["hits"] == 2 and stats["misses"] == 1


def test_compute_cache_evicts_oldest(analytic, monkeypatch):
    monkeypatch.setattr(compute_cache, "MAX_ENTRIES", 3)
    for price in (1, 2, 3, 4):
        compute_cache.cached_compute({**analytic, "purchasePrice": price * 1_000_000})
    assert compute_cache.cache_stats()["entries"] == 3
    # The first (oldest) entry was evicted; recomputing it is a miss.
    before = compute_cache.cache_stats()["misses"]
    compute_cache.cached_compute({**analytic, "purchasePrice": 1_000_000})
    assert compute_cache.cache_stats()["misses"] == before + 1


def test_compute_endpoint_uses_the_cache(analytic):
    client = TestClient(app)
    client.post("/api/compute", json={"values": analytic})
    hits_before = compute_cache.cache_stats()["hits"]
    client.post("/api/compute", json={"values": analytic})
    assert compute_cache.cache_stats()["hits"] == hits_before + 1
