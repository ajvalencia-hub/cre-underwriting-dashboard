"""Regression tests for FINDINGS.md M14: scenario PUT accepted kind and
templateId in the payload but silently ignored them. templateId is now
applied (with create's validation); a kind change is rejected, and an update
that omits kind keeps the stored one.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Template


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)

    def _override():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    yield TestClient(app)
    app.dependency_overrides.pop(get_db)
    engine.dispose()


def _make_template(client) -> str:
    db = next(app.dependency_overrides[get_db]())
    template = Template(filename="t.xlsx", file_hash="h", stored_path="/tmp/t.xlsx")
    db.add(template)
    db.commit()
    db.refresh(template)
    return template.id


def test_kind_change_is_rejected_not_ignored(client):
    created = client.post(
        "/api/scenarios",
        json={"scenarioName": "QS", "kind": "quickscreen", "inputs": {"x": 1}},
    ).json()

    resp = client.put(
        f"/api/scenarios/{created['id']}",
        json={"scenarioName": "QS", "kind": "full", "inputs": {"x": 2}},
    )
    assert resp.status_code == 400
    assert "kind" in resp.json()["detail"]


def test_update_without_kind_keeps_stored_kind(client):
    created = client.post(
        "/api/scenarios",
        json={"scenarioName": "QS", "kind": "quickscreen", "inputs": {"x": 1}},
    ).json()

    resp = client.put(
        f"/api/scenarios/{created['id']}",
        json={"scenarioName": "QS renamed", "inputs": {"x": 2}},
    )
    assert resp.status_code == 200
    assert resp.json()["kind"] == "quickscreen"
    assert resp.json()["inputs"] == {"x": 2}


def test_template_id_is_applied_on_full_scenario_update(client):
    template_a = _make_template(client)
    template_b = _make_template(client)
    created = client.post(
        "/api/scenarios",
        json={
            "scenarioName": "Deal",
            "kind": "full",
            "templateId": template_a,
            "mappingProfileId": "mp1",
            "inputs": {},
        },
    ).json()

    resp = client.put(
        f"/api/scenarios/{created['id']}",
        json={
            "scenarioName": "Deal",
            "templateId": template_b,
            "mappingProfileId": "mp1",
            "inputs": {},
        },
    )
    assert resp.status_code == 200
    assert resp.json()["templateId"] == template_b  # previously silently kept template_a


def test_full_scenario_update_requires_template_and_profile(client):
    template_a = _make_template(client)
    created = client.post(
        "/api/scenarios",
        json={
            "scenarioName": "Deal",
            "kind": "full",
            "templateId": template_a,
            "mappingProfileId": "mp1",
            "inputs": {},
        },
    ).json()

    resp = client.put(
        f"/api/scenarios/{created['id']}",
        json={"scenarioName": "Deal", "inputs": {}},
    )
    assert resp.status_code == 400

    resp = client.put(
        f"/api/scenarios/{created['id']}",
        json={
            "scenarioName": "Deal",
            "templateId": "nonexistent",
            "mappingProfileId": "mp1",
            "inputs": {},
        },
    )
    assert resp.status_code == 404
