"""H9: input change history — baseline capture, coalescing window, changed
paths (incl. one-level dict drill), retention, and restore-with-undo."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import DealSnapshot
from app.services import deal_history
from app.services.deal_history import changed_paths


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


def test_changed_paths_drills_one_level_into_dicts():
    old = {"purchasePrice": 1, "quickScreen": {"rent": 1800, "units": 20}, "gone": True}
    new = {"purchasePrice": 2, "quickScreen": {"rent": 1900, "units": 20}, "added": 1}
    assert changed_paths(old, new) == [
        "added", "gone", "purchasePrice", "quickScreen.rent",
    ]
    assert changed_paths({"a": 1}, {"a": 1}) == []


def test_first_edit_writes_baseline_then_coalesces(client):
    deal = client.post(
        "/api/deals", json={"name": "H", "inputs": {"purchasePrice": 1_000_000}}
    ).json()

    # Two rapid saves: baseline + one coalesced autosave snapshot.
    client.put(f"/api/deals/{deal['id']}", json={"inputs": {"purchasePrice": 1_100_000}})
    client.put(
        f"/api/deals/{deal['id']}",
        json={"inputs": {"purchasePrice": 1_100_000, "vacancyPct": 0.05}},
    )

    history = client.get(f"/api/deals/{deal['id']}/history").json()
    assert [h["kind"] for h in history] == ["autosave", "baseline"]
    # Coalesced changedPaths accumulate across the window's saves.
    assert history[0]["changedPaths"] == ["purchasePrice", "vacancyPct"]

    # A no-op save adds nothing.
    client.put(
        f"/api/deals/{deal['id']}",
        json={"inputs": {"purchasePrice": 1_100_000, "vacancyPct": 0.05}},
    )
    assert len(client.get(f"/api/deals/{deal['id']}/history").json()) == 2


def test_saves_outside_the_window_get_their_own_snapshot(client, session_factory):
    deal = client.post("/api/deals", json={"name": "W", "inputs": {"a": 1}}).json()
    client.put(f"/api/deals/{deal['id']}", json={"inputs": {"a": 2}})

    # Age the newest snapshot past the coalescing window.
    with session_factory() as db:
        for snapshot in db.query(DealSnapshot).all():
            snapshot.created_at = datetime.now(timezone.utc) - timedelta(minutes=11)
        db.commit()

    client.put(f"/api/deals/{deal['id']}", json={"inputs": {"a": 3}})
    history = client.get(f"/api/deals/{deal['id']}/history").json()
    assert [h["kind"] for h in history] == ["autosave", "autosave", "baseline"]
    assert history[0]["changedPaths"] == ["a"]


def test_retention_caps_snapshots_per_deal(client, session_factory, monkeypatch):
    monkeypatch.setattr(deal_history, "RETENTION_PER_DEAL", 5)
    monkeypatch.setattr(deal_history, "COALESCE_WINDOW_MINUTES", 0)  # every save = new row
    deal = client.post("/api/deals", json={"name": "R", "inputs": {"n": 0}}).json()
    for n in range(1, 10):
        client.put(f"/api/deals/{deal['id']}", json={"inputs": {"n": n}})

    history = client.get(f"/api/deals/{deal['id']}/history").json()
    assert len(history) == 5
    # Newest survive; the baseline eventually rolls off (it's history, not a pin).
    with session_factory() as db:
        newest = db.query(DealSnapshot).order_by(DealSnapshot.created_at.desc()).first()
        assert newest.inputs == {"n": 9}


def test_single_snapshot_endpoint_serves_full_inputs(client):
    """I12: the list stays metadata-only; the single-snapshot GET carries the
    inputs for diff/compare views; cross-deal access is a 404."""
    deal = client.post("/api/deals", json={"name": "D", "inputs": {"x": 1}}).json()
    client.put(f"/api/deals/{deal['id']}", json={"inputs": {"x": 2}})

    history = client.get(f"/api/deals/{deal['id']}/history").json()
    assert all("inputs" not in h for h in history)

    baseline = next(h for h in history if h["kind"] == "baseline")
    full = client.get(f"/api/deals/{deal['id']}/history/{baseline['id']}").json()
    assert full["inputs"] == {"x": 1}
    assert full["kind"] == "baseline"

    other = client.post("/api/deals", json={"name": "E", "inputs": {}}).json()
    assert (
        client.get(f"/api/deals/{other['id']}/history/{baseline['id']}").status_code == 404
    )


def test_restore_round_trip_and_undo(client):
    deal = client.post("/api/deals", json={"name": "U", "inputs": {"x": 1}}).json()
    client.put(f"/api/deals/{deal['id']}", json={"inputs": {"x": 2}})

    history = client.get(f"/api/deals/{deal['id']}/history").json()
    baseline = next(h for h in history if h["kind"] == "baseline")

    restored = client.post(
        f"/api/deals/{deal['id']}/history/{baseline['id']}/restore"
    ).json()
    assert restored["inputs"] == {"x": 1}

    # The restore is its own snapshot, so the pre-restore state is recoverable.
    history = client.get(f"/api/deals/{deal['id']}/history").json()
    assert history[0]["kind"] == "restore"
    pre_restore = next(h for h in history if h["kind"] == "autosave")
    undone = client.post(
        f"/api/deals/{deal['id']}/history/{pre_restore['id']}/restore"
    ).json()
    assert undone["inputs"] == {"x": 2}

    # Snapshot from another deal is a 404.
    other = client.post("/api/deals", json={"name": "V", "inputs": {}}).json()
    assert (
        client.post(f"/api/deals/{other['id']}/history/{baseline['id']}/restore").status_code
        == 404
    )
