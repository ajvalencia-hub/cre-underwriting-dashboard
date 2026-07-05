"""H8: assumption presets — seeding (empty-table-only, deletions stick),
CRUD, and the capturable-field whitelist enforcement."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.services.presets import PRESET_FIELD_IDS, SEED_PRESETS, seed_presets


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


@pytest.fixture
def client(session_factory):
    def _override():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    yield TestClient(app)
    app.dependency_overrides.pop(get_db)


def test_seed_values_are_whitelisted():
    """Every seed field must be capturable, or the seeds would fail their own
    whitelist on edit."""
    for seed in SEED_PRESETS:
        for field_id in seed["values"]:
            assert field_id in PRESET_FIELD_IDS, f"{seed['name']}: {field_id}"


def test_seeding_only_fills_an_empty_table(session_factory, client):
    with session_factory() as db:
        assert seed_presets(db) == len(SEED_PRESETS)
        assert seed_presets(db) == 0  # second run: no duplicates

    presets = client.get("/api/presets").json()
    names = {p["name"] for p in presets}
    assert {"Conservative", "Base Case", "Aggressive Growth"} <= names

    # Delete every preset — reseeding must NOT resurrect them mid-session.
    for preset in presets:
        client.delete(f"/api/presets/{preset['id']}")
    with session_factory() as db:
        assert seed_presets(db) == len(SEED_PRESETS)  # empty again -> reseed allowed


def test_preset_crud_and_whitelist(client):
    created = client.post(
        "/api/presets",
        json={
            "name": "My Screen",
            "values": {
                "vacancyPct": 0.06,
                "exitCapRatePct": 0.058,
                "purchasePrice": 5_000_000,  # NOT capturable — must be dropped
                "unitMix": [{"unitType": "1BR"}],  # ditto
            },
        },
    ).json()
    assert created["values"] == {"vacancyPct": 0.06, "exitCapRatePct": 0.058}
    assert created["source"] == "user"

    updated = client.put(
        f"/api/presets/{created['id']}",
        json={"name": "My Screen v2", "values": {"vacancyPct": 0.05}},
    ).json()
    assert updated["name"] == "My Screen v2"
    assert updated["values"] == {"vacancyPct": 0.05}

    assert client.delete(f"/api/presets/{created['id']}").status_code == 200
    assert client.delete(f"/api/presets/{created['id']}").status_code == 404


def test_preset_with_no_capturable_fields_rejected(client):
    response = client.post(
        "/api/presets",
        json={"name": "Empty", "values": {"purchasePrice": 1}},
    )
    assert response.status_code == 400
