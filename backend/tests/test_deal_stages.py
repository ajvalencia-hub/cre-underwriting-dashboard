"""Dealflow segregation: the stage registry (single source in
input_schema.json), status validation against the union, and typed
portfolio aggregation."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.schemas import DEAL_STAGES_BY_TYPE, DEAL_STATUSES, DealUpdate


def test_registry_shape():
    # Acquisitions keep the ORIGINAL six stages — existing deals need no
    # migration; developments get the project-lifecycle set.
    assert DEAL_STAGES_BY_TYPE["acquisition"] == [
        "screening", "underwriting", "loi", "under_contract", "closed", "dead",
    ]
    assert DEAL_STAGES_BY_TYPE["development"] == [
        "screening", "feasibility", "site_control", "entitlements",
        "pre_construction", "construction", "lease_up", "stabilized", "dead",
    ]
    # Both flows share an entry and an exit.
    for stages in DEAL_STAGES_BY_TYPE.values():
        assert stages[0] == "screening" and stages[-1] == "dead"
    # DEAL_STATUSES is the de-duplicated union, legacy values first.
    assert set(DEAL_STATUSES) == {s for v in DEAL_STAGES_BY_TYPE.values() for s in v}
    assert DEAL_STATUSES[:6] == ("screening", "underwriting", "loi",
                                 "under_contract", "closed", "dead")


def test_deal_update_validates_against_union():
    assert DealUpdate(status="construction").status == "construction"
    assert DealUpdate(status="loi").status == "loi"
    with pytest.raises(ValidationError):
        DealUpdate(status="flipping")


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


def test_development_stages_round_trip_the_api(client):
    deal = client.post("/api/deals", json={
        "name": "Tower Site", "inputs": {"dealType": "development"},
    }).json()
    assert deal["inputs"]["dealType"] == "development"  # typed from birth

    updated = client.put(f"/api/deals/{deal['id']}", json={"status": "entitlements"})
    assert updated.status_code == 200
    assert updated.json()["status"] == "entitlements"

    rejected = client.put(f"/api/deals/{deal['id']}", json={"status": "bogus"})
    assert rejected.status_code == 422

    bulk = client.post("/api/deals/bulk-status", json={
        "dealIds": [deal["id"]], "status": "construction",
    })
    assert bulk.status_code == 200
    assert client.get(f"/api/deals/{deal['id']}").json()["status"] == "construction"

    bad_bulk = client.post("/api/deals/bulk-status", json={
        "dealIds": [deal["id"]], "status": "bogus",
    })
    assert bad_bulk.status_code in (400, 422)
