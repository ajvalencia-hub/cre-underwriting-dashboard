"""Global test isolation for non-request-scoped DB access.

app/services/settings.py and app/services/agent/model_router.py both open
their own short-lived session via database.SessionLocal — deliberately,
since they're called from code with no FastAPI Depends(get_db) session in
scope (provider adapters, document_classifier.py, llm_extraction.py). Left
unpatched, EVERY test that transitively touches settings resolution or
usage recording (which, after M3, includes any classification/extraction
call — even ones that don't go through an HTTP client at all) would read
and write the real developer-machine SQLite file, not a test double. This
is a real, silent risk on a machine with a locally reachable Ollama
instance (M2's routing.classification.provider defaults to "ollama" —
without this fixture, a classification test could attempt a genuine
network call and log a real LlmUsageEvent row into the dev DB).

This autouse fixture gives every test its own throwaway in-memory engine
for those two modules by default. Tests that need their OWN specific
isolated engine (e.g. to assert read-your-own-write behavior, like
test_settings.py) layer an additional monkeypatch on top in their own
fixture — since autouse fixtures resolve before test-requested ones,
the more specific override wins, this default is just a safety net, not a
behavior tests need to know about.
"""

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.services import settings as settings_service
from app.services.agent import model_router


@pytest.fixture(autouse=True)
def _isolate_bare_db_sessions(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine)
    monkeypatch.setattr(settings_service, "SessionLocal", test_session)
    monkeypatch.setattr(model_router, "SessionLocal", test_session)
    yield
    engine.dispose()


def _no_network(*args, **kwargs):
    raise httpx.ConnectError("network calls are blocked by default in tests — see conftest.py")


@pytest.fixture(autouse=True)
def _block_real_network_calls(monkeypatch):
    """M2/M3: routing.classification.provider/routing.extraction.provider/
    routing.agent.provider all default to "ollama" — on a dev machine with a
    real local Ollama instance reachable (true for this repo's own dev
    environment), an unstubbed classification/extraction/agent test would
    silently make a GENUINE network call instead of failing fast, violating
    this repo's established "no live network calls in tests" discipline
    (stated directly in the K2 provider tests' own docstrings) and adding
    multi-second real I/O latency to tests that have nothing to do with
    Ollama at all (confirmed directly: several document-upload/classification
    tests got 2-4s slower the moment M3 wired classification through
    model_router). Blocked by default via httpx.post/get; any test that
    wants to exercise a real (mocked) HTTP call — e.g. test_ollama_provider.py
    — already monkeypatches httpx.post/get itself, which simply overrides
    this default for that test."""
    monkeypatch.setattr(httpx, "post", _no_network)
    monkeypatch.setattr(httpx, "get", _no_network)
