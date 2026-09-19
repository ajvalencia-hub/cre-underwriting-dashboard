"""Roadmap #28: local investment-committee sign-off — states, approvals,
reasons, the snapshot a submission stores, and the input lock."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app

_DEAL = json.loads((Path(__file__).parent / "fixtures" / "analytic_acquisition.json").read_text())
_DEAL.pop("_comment", None)


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def _override():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    yield TestClient(app)
    app.dependency_overrides.pop(get_db)
    engine.dispose()


def _new_deal(client, inputs=None) -> str:
    return client.post("/api/deals", json={"name": "IC deal", "inputs": inputs or dict(_DEAL)}).json()["id"]


def _step(client, deal_id, kind, actor="Ana", comment="", **extra):
    return client.post(
        f"/api/deals/{deal_id}/ic/events",
        json={"kind": kind, "actor": actor, "comment": comment, **extra},
    )


def test_a_new_deal_is_draft_and_unlocked(client):
    deal_id = _new_deal(client)
    summary = client.get(f"/api/deals/{deal_id}/ic").json()
    assert summary["state"] == "draft"
    assert summary["locked"] is False
    assert summary["lastSubmission"] is None


def test_submit_stores_the_computed_snapshot_and_locks_inputs(client):
    deal_id = _new_deal(client)
    summary = _step(client, deal_id, "submit", comment="Base case").json()
    assert summary["state"] == "submitted"
    assert summary["locked"] is True
    submission = summary["lastSubmission"]
    assert submission["inputs"]["purchasePrice"] == 1_000_000
    assert submission["outputs"]["goingInCapRate"] == pytest.approx(0.08)
    assert "quickScreen" not in submission["inputs"]

    changed = dict(_DEAL, purchasePrice=1_100_000)
    response = client.put(f"/api/deals/{deal_id}", json={"inputs": changed})
    assert response.status_code == 409
    assert "Reopen it with a reason" in response.json()["detail"]


def test_the_napkin_and_dates_stay_editable_while_locked(client):
    deal_id = _new_deal(client)
    _step(client, deal_id, "submit")
    edited = dict(_DEAL, quickScreen={"rent": 2_000}, criticalDates=[{"label": "Closing", "date": "2026-12-01"}])
    assert client.put(f"/api/deals/{deal_id}", json={"inputs": edited}).status_code == 200
    # Which napkin is showing is a view choice, not an underwriting input.
    switched = dict(edited, quickScreenMode="acquisition", acquisitionQuickScreen={"price": 1})
    assert client.put(f"/api/deals/{deal_id}", json={"inputs": switched}).status_code == 200


def test_a_deal_that_cannot_compute_cannot_be_submitted(client):
    deal_id = _new_deal(client, {"dealType": "acquisition"})
    response = _step(client, deal_id, "submit")
    assert response.status_code == 400
    assert "Missing" in response.json()["detail"]
    assert client.get(f"/api/deals/{deal_id}/ic").json()["state"] == "draft"


def test_approval_needs_the_required_number_of_distinct_approvers(client):
    deal_id = _new_deal(client)
    _step(client, deal_id, "submit", requiredApprovals=2)
    assert _step(client, deal_id, "approve", actor="Ben").json()["state"] == "submitted"
    # The same person (any spacing or case) doesn't count twice.
    repeat = _step(client, deal_id, "approve", actor="  ben ")
    assert repeat.status_code == 409
    summary = _step(client, deal_id, "approve", actor="Cleo").json()
    assert summary["state"] == "approved"
    assert summary["approvers"] == ["Ben", "Cleo"]
    assert summary["locked"] is True


@pytest.mark.parametrize("kind", ["reject", "return", "reopen"])
def test_saying_no_or_reopening_needs_a_reason(client, kind):
    deal_id = _new_deal(client)
    _step(client, deal_id, "submit")
    response = _step(client, deal_id, kind, comment="  ")
    assert response.status_code == 400
    assert "reason" in response.json()["detail"]


def test_reject_locks_and_reopen_unlocks_with_the_reason_logged(client):
    deal_id = _new_deal(client)
    _step(client, deal_id, "submit")
    assert _step(client, deal_id, "reject", actor="Ben", comment="Exit cap too tight").json()["state"] == "rejected"
    changed = dict(_DEAL, exitCapRatePct=0.085)
    assert client.put(f"/api/deals/{deal_id}", json={"inputs": changed}).status_code == 409

    summary = _step(client, deal_id, "reopen", comment="Widen the exit cap").json()
    assert summary["state"] == "draft"
    assert summary["lastSubmission"]["current"] is False
    assert [e["kind"] for e in summary["events"]] == ["submit", "reject", "reopen"]
    assert summary["events"][-1]["comment"] == "Widen the exit cap"
    assert client.put(f"/api/deals/{deal_id}", json={"inputs": changed}).status_code == 200


def test_steps_out_of_order_are_refused(client):
    deal_id = _new_deal(client)
    assert _step(client, deal_id, "approve").status_code == 409
    _step(client, deal_id, "submit")
    assert _step(client, deal_id, "submit").status_code == 409
    assert _step(client, deal_id, "comment", actor="", comment="hi").status_code == 400


def test_history_restore_respects_the_lock(client):
    deal_id = _new_deal(client)
    client.put(f"/api/deals/{deal_id}", json={"inputs": dict(_DEAL, purchasePrice=900_000)})
    snapshot_id = client.get(f"/api/deals/{deal_id}/history").json()[-1]["id"]
    _step(client, deal_id, "submit")
    response = client.post(f"/api/deals/{deal_id}/history/{snapshot_id}/restore")
    assert response.status_code == 409


def test_ic_states_list_non_draft_deals(client):
    draft = _new_deal(client)
    submitted = _new_deal(client)
    _step(client, submitted, "submit")
    states = client.get("/api/ic/states").json()
    assert states == {submitted: "submitted"}
    assert draft not in states


def test_export_import_carries_the_log(client):
    deal_id = _new_deal(client)
    _step(client, deal_id, "submit", comment="Base case")
    _step(client, deal_id, "approve", actor="Ben", comment="Good basis")
    bundle = client.get(f"/api/deals/{deal_id}/export").json()
    assert [e["kind"] for e in bundle["icEvents"]] == ["submit", "approve"]

    imported = client.post("/api/deals/import", json={"bundle": bundle}).json()
    summary = client.get(f"/api/deals/{imported['id']}/ic").json()
    assert summary["state"] == "approved"
    assert summary["approvers"] == ["Ben"]
    assert summary["lastSubmission"]["outputs"]["goingInCapRate"] == pytest.approx(0.08)
    assert any("investment-committee" in w for w in imported["importWarnings"])


def test_deleting_a_deal_deletes_its_log(client):
    deal_id = _new_deal(client)
    _step(client, deal_id, "submit")
    client.delete(f"/api/deals/{deal_id}")
    assert client.get("/api/ic/states").json() == {}
