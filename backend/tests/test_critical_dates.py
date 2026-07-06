"""J11: critical dates — stored in the deal's inputs blob, so CRUD is the
ordinary deal update; these tests pin the share-HTML section and the
export/import round-trip. Ordering/overdue logic lives in the frontend lib
(criticalDates.test.ts)."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app

FIXTURES = Path(__file__).parent / "fixtures"

DATES = [
    {"id": "a", "label": "LOI expiry", "date": "2026-07-15", "notes": "seller extension possible"},
    {"id": "b", "label": "Closing", "date": "2026-09-01", "notes": ""},
]


@pytest.fixture
def client():
    db_engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
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


def _dated_deal(client) -> dict:
    inputs = json.loads((FIXTURES / "analytic_acquisition.json").read_text())
    inputs["criticalDates"] = DATES
    deal = client.post("/api/deals", json={"name": "Dated Deal"}).json()
    return client.put(f"/api/deals/{deal['id']}", json={"inputs": inputs}).json()


def test_crud_via_deal_inputs(client):
    deal = _dated_deal(client)
    assert deal["inputs"]["criticalDates"] == DATES
    # Update (edit one, delete one) is just another inputs PUT.
    edited = [{**DATES[0], "date": "2026-07-20"}]
    inputs = {**deal["inputs"], "criticalDates": edited}
    updated = client.put(f"/api/deals/{deal['id']}", json={"inputs": inputs}).json()
    assert updated["inputs"]["criticalDates"] == edited


def test_share_html_includes_dates_sorted(client):
    deal = _dated_deal(client)
    html = client.get(f"/api/deals/{deal['id']}/share.html").text
    assert "CRITICAL DATES" in html
    assert "LOI expiry" in html and "2026-09-01" in html
    assert "seller extension possible" in html
    # Sorted ascending: LOI expiry renders before Closing.
    assert html.index("LOI expiry") < html.index("Closing")
    # No dates -> no section (never an empty header).
    plain = client.post("/api/deals", json={"name": "Undated"}).json()
    assert "CRITICAL DATES" not in client.get(f"/api/deals/{plain['id']}/share.html").text


def test_bundle_round_trip_preserves_dates(client):
    deal = _dated_deal(client)
    bundle = client.get(f"/api/deals/{deal['id']}/export").json()
    imported = client.post("/api/deals/import", json={"bundle": bundle}).json()
    fetched = client.get(f"/api/deals/{imported['id']}").json()
    assert fetched["inputs"]["criticalDates"] == DATES
