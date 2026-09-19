"""Pipeline numbers (roadmap #18): key metrics for every deal from its
saved inputs, or what it's missing."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app

_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def client():
    db_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(db_engine)
    TestSession = sessionmaker(bind=db_engine)

    def _override():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    yield TestClient(app)
    app.dependency_overrides.pop(get_db)
    db_engine.dispose()


def test_metrics_for_complete_and_incomplete_deals(client):
    analytic = json.loads((_FIXTURES / "analytic_acquisition.json").read_text())
    analytic.pop("_comment")
    full = client.post("/api/deals", json={"name": "Full", "inputs": analytic}).json()["id"]
    empty = client.post("/api/deals", json={"name": "Empty", "inputs": {"dealType": "acquisition"}}).json()["id"]
    metrics = client.get("/api/deals/metrics").json()
    assert metrics[full]["status"] == "ok"
    assert metrics[full]["equity"] == pytest.approx(400_000)
    assert metrics[full]["totalCost"] == pytest.approx(1_000_000)
    assert metrics[full]["leveredIrr"] == pytest.approx(0.115718, abs=1e-6)
    assert metrics[empty]["status"] == "incomplete" and metrics[empty]["missing"]
