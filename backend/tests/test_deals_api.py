"""F1: deal CRUD, autosave round-trip, scenario-deal scoping, and the legacy
backfill migration (scenarios that predate deals get a Default Deal owner).
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db, run_migrations
from app.main import app


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


def test_deal_crud_round_trip(client):
    created = client.post("/api/deals", json={"name": "Maple Street"}).json()
    assert created["name"] == "Maple Street"
    assert created["inputs"] == {}

    # Autosave round-trip: PUT the inputs blob, read it back intact.
    inputs = {"dealName": "Maple Street", "purchasePrice": 1000000, "quickScreen": {"rent": 1800}}
    updated = client.put(f"/api/deals/{created['id']}", json={"inputs": inputs}).json()
    assert updated["inputs"] == inputs

    fetched = client.get(f"/api/deals/{created['id']}").json()
    assert fetched["inputs"]["quickScreen"] == {"rent": 1800}

    assert client.delete(f"/api/deals/{created['id']}").json() == {"deleted": True}
    assert client.get(f"/api/deals/{created['id']}").status_code == 404


def test_partial_update_does_not_clobber_other_fields(client):
    deal = client.post("/api/deals", json={"name": "A", "inputs": {"x": 1}}).json()

    renamed = client.put(f"/api/deals/{deal['id']}", json={"name": "B"}).json()
    assert renamed["inputs"] == {"x": 1}  # inputs untouched by a name-only PUT

    with_template = client.put(
        f"/api/deals/{deal['id']}", json={"activeTemplateId": "t1", "activeMappingProfileId": "m1"}
    ).json()
    assert with_template["name"] == "B"
    assert with_template["activeTemplateId"] == "t1"

    # inputs-only PUT (the autosave) must not clear the template selection.
    autosaved = client.put(f"/api/deals/{deal['id']}", json={"inputs": {"x": 2}}).json()
    assert autosaved["activeTemplateId"] == "t1"
    assert autosaved["activeMappingProfileId"] == "m1"


def test_blank_name_rejected(client):
    assert client.post("/api/deals", json={"name": "   "}).status_code == 400
    deal = client.post("/api/deals", json={"name": "Ok"}).json()
    assert client.put(f"/api/deals/{deal['id']}", json={"name": ""}).status_code == 400


def test_scenarios_scope_to_deal_and_cascade_on_delete(client):
    deal_a = client.post("/api/deals", json={"name": "A"}).json()
    deal_b = client.post("/api/deals", json={"name": "B"}).json()

    for name, deal in (("s1", deal_a), ("s2", deal_a), ("s3", deal_b)):
        client.post(
            "/api/scenarios",
            json={"scenarioName": name, "kind": "quickscreen", "dealId": deal["id"], "inputs": {}},
        )

    in_a = client.get(f"/api/scenarios?deal_id={deal_a['id']}").json()
    assert sorted(s["scenarioName"] for s in in_a) == ["s1", "s2"]
    assert all(s["dealId"] == deal_a["id"] for s in in_a)

    client.delete(f"/api/deals/{deal_a['id']}")
    assert client.get(f"/api/scenarios?deal_id={deal_a['id']}").json() == []
    remaining = client.get("/api/scenarios").json()
    assert [s["scenarioName"] for s in remaining] == ["s3"]


def test_legacy_backfill_assigns_orphans_to_default_deal(tmp_path):
    """Simulate a pre-deals database: a scenarios table without deal_id and an
    existing row. run_migrations must add the column, create Default Deal, and
    adopt the orphan — and stay idempotent on the second run."""
    eng = create_engine(f"sqlite:///{tmp_path / 'legacy.sqlite3'}")
    with eng.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE scenarios (
                    id VARCHAR PRIMARY KEY,
                    scenario_name VARCHAR,
                    kind VARCHAR DEFAULT 'full',
                    template_id VARCHAR,
                    mapping_profile_id VARCHAR,
                    inputs JSON,
                    outputs JSON,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO scenarios (id, scenario_name, kind, inputs, outputs) "
                "VALUES ('legacy1', 'Old Scenario', 'quickscreen', '{}', '{}')"
            )
        )
    # The deals table itself comes from create_all on startup.
    Base.metadata.create_all(eng)

    run_migrations(eng)

    with eng.connect() as conn:
        deal_row = conn.execute(text("SELECT id, name FROM deals")).fetchone()
        assert deal_row is not None and deal_row.name == "Default Deal"
        scenario_deal = conn.execute(
            text("SELECT deal_id FROM scenarios WHERE id = 'legacy1'")
        ).scalar()
        assert scenario_deal == deal_row.id

    run_migrations(eng)  # idempotent: second run must not duplicate the deal
    with eng.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM deals")).scalar() == 1
    eng.dispose()


def test_deal_status_lifecycle(client):
    """H7: new deals start at 'screening'; status PUTs update it without
    clobbering anything; invalid stages are rejected."""
    deal = client.post("/api/deals", json={"name": "Pipeline Deal", "inputs": {"x": 1}}).json()
    assert deal["status"] == "screening"

    moved = client.put(f"/api/deals/{deal['id']}", json={"status": "underwriting"}).json()
    assert moved["status"] == "underwriting"
    assert moved["inputs"] == {"x": 1}  # untouched by a status-only PUT

    autosaved = client.put(f"/api/deals/{deal['id']}", json={"inputs": {"x": 2}}).json()
    assert autosaved["status"] == "underwriting"  # untouched by an inputs-only PUT

    assert client.put(f"/api/deals/{deal['id']}", json={"status": "bogus"}).status_code == 422


def test_deals_status_migration(tmp_path):
    """A pre-H7 deals table gains the status column with 'screening'
    backfilled, idempotently."""
    eng = create_engine(f"sqlite:///{tmp_path / 'pre_status.sqlite3'}")
    with eng.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE deals (
                    id VARCHAR PRIMARY KEY,
                    name VARCHAR,
                    inputs JSON,
                    active_template_id VARCHAR,
                    active_mapping_profile_id VARCHAR,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        conn.execute(
            text("INSERT INTO deals (id, name, inputs) VALUES ('d1', 'Old Deal', '{}')")
        )

    run_migrations(eng)
    with eng.connect() as conn:
        assert conn.execute(text("SELECT status FROM deals WHERE id = 'd1'")).scalar() == "screening"

    run_migrations(eng)  # idempotent
    with eng.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM deals")).scalar() == 1
    eng.dispose()
