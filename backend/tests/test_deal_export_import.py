"""G7: deal export/import — round-trip equality, version rejection, id
rewriting, and template-placeholder handling."""

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


def _make_deal_with_scenarios(client) -> dict:
    deal = client.post("/api/deals", json={"name": "Maple Court"}).json()
    inputs = {"dealType": "acquisition", "purchasePrice": 1_000_000, "quickScreen": {"rent": 1800}}
    client.put(f"/api/deals/{deal['id']}", json={"inputs": inputs})
    client.post(
        "/api/scenarios",
        json={
            "scenarioName": "Base", "kind": "quickscreen", "dealId": deal["id"],
            "inputs": {"rent": 1800}, "outputs": {"metrics": {"leveredIrr": 0.12}},
        },
    )
    scenario2 = client.post(
        "/api/scenarios",
        json={"scenarioName": "Upside", "kind": "quickscreen", "dealId": deal["id"], "inputs": {"rent": 2000}},
    ).json()
    client.put(
        f"/api/scenarios/{scenario2['id']}/sensitivity",
        json={"sensitivity": {"description": "d", "header": ["h"], "rows": [["r"]], "run": {}}},
    )
    return client.get(f"/api/deals/{deal['id']}").json()


def test_export_import_round_trip(client):
    deal = _make_deal_with_scenarios(client)
    bundle = client.get(f"/api/deals/{deal['id']}/export").json()

    assert bundle["exportKind"] == "cre-dashboard-deal"
    assert bundle["schemaVersion"] == 1
    assert bundle["deal"]["inputs"]["purchasePrice"] == 1_000_000
    assert len(bundle["scenarios"]) == 2

    imported = client.post("/api/deals/import", json={"bundle": bundle}).json()
    assert imported["name"] == "Maple Court (imported)"
    assert imported["id"] != deal["id"]  # id rewriting
    assert imported["inputs"] == deal["inputs"]  # inputs round-trip incl. quickScreen
    assert imported["importedScenarios"] == 2

    scenarios = client.get(f"/api/scenarios?deal_id={imported['id']}").json()
    by_name = {s["scenarioName"]: s for s in scenarios}
    assert set(by_name) == {"Base", "Upside"}
    assert by_name["Base"]["dealId"] == imported["id"]
    assert by_name["Base"]["inputs"] == {"rent": 1800}
    assert by_name["Upside"]["sensitivity"]["description"] == "d"  # saved runs travel


def test_unsupported_version_rejected(client):
    deal = _make_deal_with_scenarios(client)
    bundle = client.get(f"/api/deals/{deal['id']}/export").json()
    bundle["schemaVersion"] = 99
    resp = client.post("/api/deals/import", json={"bundle": bundle})
    assert resp.status_code == 400
    assert "schemaVersion" in resp.json()["detail"]

    not_a_bundle = client.post("/api/deals/import", json={"bundle": {"foo": 1}})
    assert not_a_bundle.status_code == 400


def test_template_references_become_placeholders_with_warnings(client):
    db = next(app.dependency_overrides[get_db]())
    template = Template(filename="model.xlsx", file_hash="h", stored_path="/tmp/m.xlsx")
    db.add(template)
    db.commit()
    db.refresh(template)

    deal = client.post("/api/deals", json={"name": "Templated"}).json()
    client.put(
        f"/api/deals/{deal['id']}",
        json={"activeTemplateId": template.id, "activeMappingProfileId": "mp1"},
    )
    client.post(
        "/api/scenarios",
        json={
            "scenarioName": "Full", "kind": "full", "dealId": deal["id"],
            "templateId": template.id, "mappingProfileId": "mp1", "inputs": {},
        },
    )

    bundle = client.get(f"/api/deals/{deal['id']}/export").json()
    assert bundle["activeTemplate"]["filename"] == "model.xlsx"

    imported = client.post("/api/deals/import", json={"bundle": bundle}).json()
    assert imported["activeTemplateId"] is None  # placeholder, not a dangling id
    assert any("model.xlsx" in w for w in imported["importWarnings"])

    scenarios = client.get(f"/api/scenarios?deal_id={imported['id']}").json()
    assert scenarios[0]["templateId"] is None
    assert any("re-link" in w for w in imported["importWarnings"])


def test_import_never_merges(client):
    deal = _make_deal_with_scenarios(client)
    bundle = client.get(f"/api/deals/{deal['id']}/export").json()
    client.post("/api/deals/import", json={"bundle": bundle})
    client.post("/api/deals/import", json={"bundle": bundle})
    names = [d["name"] for d in client.get("/api/deals").json()]
    assert names.count("Maple Court (imported)") == 2  # two independent deals
