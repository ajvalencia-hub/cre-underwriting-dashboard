"""Run 6: optional API token gate, deal archive (soft delete) and clone."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth, config
from app.database import Base, get_db, run_migrations
from app.main import app


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


# --- token gate ---------------------------------------------------------------

def test_no_token_configured_means_no_gate(client, monkeypatch):
    monkeypatch.setattr(config, "CRE_API_TOKEN", "")
    assert client.get("/api/deals").status_code == 200
    status = client.get("/api/auth/status").json()
    assert status == {"required": False, "authenticated": True}


def test_token_gate_blocks_and_accepts_header_and_cookie(client, monkeypatch):
    monkeypatch.setattr(config, "CRE_API_TOKEN", "s3cret-token")
    # Public routes stay open.
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/auth/status").json() == {"required": True, "authenticated": False}
    # Everything else is a 401 with a challenge.
    blocked = client.get("/api/deals")
    assert blocked.status_code == 401
    assert blocked.headers["www-authenticate"] == "Bearer"
    assert client.post("/api/deals", json={"name": "x"}).status_code == 401

    # Bearer header and X-API-Token both work; wrong values do not.
    assert client.get("/api/deals", headers={"Authorization": "Bearer s3cret-token"}).status_code == 200
    assert client.get("/api/deals", headers={"X-API-Token": "s3cret-token"}).status_code == 200
    assert client.get("/api/deals", headers={"Authorization": "Bearer nope"}).status_code == 401

    # Login sets an HttpOnly session cookie that carries an HMAC, never the token.
    bad = client.post("/api/auth/login", json={"token": "wrong"})
    assert bad.status_code == 401
    ok = client.post("/api/auth/login", json={"token": "s3cret-token"})
    assert ok.status_code == 200
    cookie = client.cookies.get(auth.SESSION_COOKIE)
    assert cookie and "s3cret-token" not in cookie
    assert "httponly" in ok.headers["set-cookie"].lower()
    assert client.get("/api/deals").status_code == 200
    assert client.get("/api/auth/status").json()["authenticated"] is True

    # Rotating the token invalidates the old cookie; logout clears it.
    monkeypatch.setattr(config, "CRE_API_TOKEN", "rotated")
    assert client.get("/api/deals").status_code == 401
    monkeypatch.setattr(config, "CRE_API_TOKEN", "s3cret-token")
    assert client.get("/api/deals").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/deals").status_code == 401


def test_non_api_paths_are_never_gated(client, monkeypatch):
    monkeypatch.setattr(config, "CRE_API_TOKEN", "tok")
    # The SPA (or a 404 for it in tests) must not turn into a 401.
    assert client.get("/").status_code != 401


# --- archive ---------------------------------------------------------------

def _deal(client, name):
    return client.post("/api/deals", json={"name": name}).json()["id"]


def test_archive_hides_deal_from_list_portfolio_and_search(client):
    keep = _deal(client, "Keeper Court")
    gone = _deal(client, "Goner Court")
    client.post(f"/api/deals/{gone}/notes", json={"body": "remember this"})

    out = client.post(f"/api/deals/{gone}/archive").json()
    assert out["archivedAt"] is not None
    # Idempotent: archiving again keeps the original timestamp.
    assert client.post(f"/api/deals/{gone}/archive").json()["archivedAt"] == out["archivedAt"]

    ids = {d["id"] for d in client.get("/api/deals").json()}
    assert ids == {keep}
    all_ids = {d["id"] for d in client.get("/api/deals?includeArchived=true").json()}
    assert all_ids == {keep, gone}
    # Still fetchable directly (nothing was destroyed).
    assert client.get(f"/api/deals/{gone}").status_code == 200
    assert client.get(f"/api/deals/{gone}/notes").json()[0]["body"] == "remember this"

    search = client.get("/api/search?q=court").json()["groups"]
    titles = [i["title"] for g in search if g["kind"] == "deals" for i in g["items"]]
    assert titles == ["Keeper Court"]
    notes = [i for g in search if g["kind"] == "notes" for i in g["items"]]
    assert notes == []
    portfolio_ids = {d["id"] for d in client.get("/api/portfolio").json()["deals"]} | {
        d["id"] for d in client.get("/api/portfolio").json()["excluded"]
    }
    assert gone not in portfolio_ids

    back = client.post(f"/api/deals/{gone}/unarchive").json()
    assert back["archivedAt"] is None
    assert {d["id"] for d in client.get("/api/deals").json()} == {keep, gone}


def test_archived_at_migration_is_idempotent(tmp_path):
    from sqlalchemy import text

    eng = create_engine(f"sqlite:///{tmp_path / 'old.sqlite3'}")
    with eng.begin() as conn:
        conn.execute(text(
            "CREATE TABLE deals (id VARCHAR PRIMARY KEY, name VARCHAR, inputs JSON, "
            "status VARCHAR, active_template_id VARCHAR, active_mapping_profile_id VARCHAR, "
            "created_at DATETIME, updated_at DATETIME)"
        ))
        conn.execute(text("INSERT INTO deals (id, name, inputs, status) VALUES ('d1', 'Old', '{}', 'screening')"))
    run_migrations(eng)
    run_migrations(eng)
    assert "archived_at" in {c["name"] for c in inspect(eng).get_columns("deals")}
    with eng.connect() as conn:
        assert conn.execute(text("SELECT archived_at FROM deals")).scalar() is None
    eng.dispose()


# --- clone -----------------------------------------------------------------

def test_clone_copies_inputs_stage_and_scenarios_but_not_notes(client):
    source = _deal(client, "Original")
    client.put(f"/api/deals/{source}", json={
        "inputs": {"dealType": "acquisition", "purchasePrice": 1000000, "_omWizard": {"step": 2}},
        "status": "underwriting",
    })
    client.post(f"/api/deals/{source}/notes", json={"body": "private"})
    client.post("/api/scenarios", json={
        "scenarioName": "Base", "kind": "quickscreen", "dealId": source,
        "inputs": {"a": 1}, "outputs": {"b": 2},
    })

    clone = client.post(f"/api/deals/{source}/clone").json()
    assert clone["id"] != source
    assert clone["name"] == "Copy of Original"
    assert clone["status"] == "underwriting"
    assert clone["inputs"]["purchasePrice"] == 1000000
    assert clone["inputs"]["dealName"] == "Copy of Original"
    assert "_omWizard" not in clone["inputs"]
    assert clone["archivedAt"] is None

    cloned_scenarios = client.get(f"/api/scenarios?deal_id={clone['id']}").json()
    assert [s["scenarioName"] for s in cloned_scenarios] == ["Base"]
    assert cloned_scenarios[0]["id"] != client.get(f"/api/scenarios?deal_id={source}").json()[0]["id"]
    assert client.get(f"/api/deals/{clone['id']}/notes").json() == []
    assert client.get(f"/api/deals/{clone['id']}/history").json() == []

    # Editing the clone does not touch the source.
    client.put(f"/api/deals/{clone['id']}", json={"inputs": {"purchasePrice": 5}})
    assert client.get(f"/api/deals/{source}").json()["inputs"]["purchasePrice"] == 1000000

    named = client.post(f"/api/deals/{source}/clone", json={"name": "Downside case"}).json()
    assert named["name"] == "Downside case"
    assert client.post("/api/deals/nope/clone").status_code == 404
