"""K4: HTTP surface for the agent — thread get-or-create, message posting,
and the ordinary FastAPI validation paths (missing deal, empty content)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.services.agent import runner
from app.services.agent.providers.types import ChatResult, ToolCall, Usage


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


def _stub_end_turn(monkeypatch, text: str):
    def fake_chat_with(provider_name, messages, tools, system):
        return ChatResult(text=text, tool_calls=[], usage=Usage(2, 2), stop_reason="end_turn")

    monkeypatch.setattr(runner, "chat_with", fake_chat_with)


def _stub_sequence(monkeypatch, results: list[ChatResult]):
    it = iter(results)

    def fake_chat_with(provider_name, messages, tools, system):
        return next(it)

    monkeypatch.setattr(runner, "chat_with", fake_chat_with)


def _propose_one(client, monkeypatch, deal_id: str, changes: dict, rationale: str = "test") -> str:
    """Drives one turn that proposes `changes` and returns the new proposal id."""
    _stub_sequence(monkeypatch, [
        ChatResult(
            text="",
            tool_calls=[ToolCall(
                id="c1", name="propose_input_changes",
                arguments={"currentValues": {}, "changes": changes, "rationale": rationale},
            )],
            usage=Usage(1, 1), stop_reason="tool_use",
        ),
        ChatResult(text="Proposed a change.", tool_calls=[], usage=Usage(1, 1), stop_reason="end_turn"),
    ])
    turn = client.post(f"/api/agent/threads/{deal_id}/messages", json={"content": "propose something"}).json()
    return turn["proposals"][0]["id"]


def test_get_thread_404s_for_missing_deal(client):
    resp = client.get("/api/agent/threads/not-a-real-deal")
    assert resp.status_code == 404


def test_get_thread_creates_an_empty_thread_for_a_real_deal(client):
    deal = client.post("/api/deals", json={"name": "Test Deal"}).json()
    resp = client.get(f"/api/agent/threads/{deal['id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["dealId"] == deal["id"]
    assert body["messages"] == []
    assert body["proposals"] == []


def test_post_message_happy_path(client, monkeypatch):
    _stub_end_turn(monkeypatch, "Hi, how can I help with this deal?")
    deal = client.post("/api/deals", json={"name": "Test Deal"}).json()

    resp = client.post(f"/api/agent/threads/{deal['id']}/messages", json={"content": "hello"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "Hi, how can I help with this deal?"
    assert body["threadId"]

    # And the thread now shows both messages on a subsequent GET.
    thread_resp = client.get(f"/api/agent/threads/{deal['id']}").json()
    assert len(thread_resp["messages"]) == 2
    assert thread_resp["messages"][0]["role"] == "user"
    assert thread_resp["messages"][1]["role"] == "assistant"


def test_post_message_reuses_the_same_thread_across_calls(client, monkeypatch):
    _stub_end_turn(monkeypatch, "ok")
    deal = client.post("/api/deals", json={"name": "Test Deal"}).json()

    first = client.post(f"/api/agent/threads/{deal['id']}/messages", json={"content": "one"}).json()
    second = client.post(f"/api/agent/threads/{deal['id']}/messages", json={"content": "two"}).json()
    assert first["threadId"] == second["threadId"]


def test_post_message_404s_for_missing_deal(client):
    resp = client.post("/api/agent/threads/not-a-real-deal/messages", json={"content": "hi"})
    assert resp.status_code == 404


def test_post_message_rejects_empty_content(client):
    deal = client.post("/api/deals", json={"name": "Test Deal"}).json()
    resp = client.post(f"/api/agent/threads/{deal['id']}/messages", json={"content": "   "})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# K7: proposal approve / reject
# ---------------------------------------------------------------------------

def test_approve_proposal_applies_changes_via_history_kind_agent(client, monkeypatch):
    deal = client.post("/api/deals", json={"name": "Test Deal"}).json()
    client.put(f"/api/deals/{deal['id']}", json={"inputs": {"purchasePrice": 1000000}})
    proposal_id = _propose_one(client, monkeypatch, deal["id"], {"purchasePrice": 1100000})

    resp = client.post(f"/api/agent/proposals/{proposal_id}/approve", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["deal"]["inputs"]["purchasePrice"] == 1100000
    assert body["proposal"]["status"] == "approved"

    history = client.get(f"/api/deals/{deal['id']}/history").json()
    assert any(h["kind"] == "agent" for h in history)


def test_approve_proposal_marks_other_pending_proposals_stale(client, monkeypatch):
    deal = client.post("/api/deals", json={"name": "Test Deal"}).json()
    _stub_sequence(monkeypatch, [
        ChatResult(
            text="",
            tool_calls=[
                ToolCall(id="c1", name="propose_input_changes",
                          arguments={"currentValues": {}, "changes": {"purchasePrice": 900000}, "rationale": "a"}),
                ToolCall(id="c2", name="propose_input_changes",
                          arguments={"currentValues": {}, "changes": {"purchasePrice": 950000}, "rationale": "b"}),
            ],
            usage=Usage(1, 1), stop_reason="tool_use",
        ),
        ChatResult(text="Two options.", tool_calls=[], usage=Usage(1, 1), stop_reason="end_turn"),
    ])
    turn = client.post(f"/api/agent/threads/{deal['id']}/messages", json={"content": "give me options"}).json()
    first_id, second_id = [p["id"] for p in turn["proposals"]]

    client.post(f"/api/agent/proposals/{first_id}/approve", json={})

    thread = client.get(f"/api/agent/threads/{deal['id']}").json()
    statuses = {p["id"]: p["status"] for p in thread["proposals"]}
    assert statuses[first_id] == "approved"
    assert statuses[second_id] == "stale"


def test_approve_already_approved_proposal_is_400(client, monkeypatch):
    deal = client.post("/api/deals", json={"name": "Test Deal"}).json()
    proposal_id = _propose_one(client, monkeypatch, deal["id"], {"purchasePrice": 900000})

    client.post(f"/api/agent/proposals/{proposal_id}/approve", json={})
    again = client.post(f"/api/agent/proposals/{proposal_id}/approve", json={})
    assert again.status_code == 400


def test_approve_proposal_404s_for_missing_id(client):
    resp = client.post("/api/agent/proposals/not-real/approve", json={})
    assert resp.status_code == 404


def test_reject_proposal_marks_rejected_and_appends_note(client, monkeypatch):
    deal = client.post("/api/deals", json={"name": "Test Deal"}).json()
    proposal_id = _propose_one(client, monkeypatch, deal["id"], {"purchasePrice": 900000})

    resp = client.post(f"/api/agent/proposals/{proposal_id}/reject", json={"note": "too aggressive"})
    assert resp.status_code == 200
    assert resp.json()["proposal"]["status"] == "rejected"

    thread = client.get(f"/api/agent/threads/{deal['id']}").json()
    assert any("too aggressive" in m["content"] for m in thread["messages"])


def test_reject_already_rejected_proposal_is_400(client, monkeypatch):
    deal = client.post("/api/deals", json={"name": "Test Deal"}).json()
    proposal_id = _propose_one(client, monkeypatch, deal["id"], {"purchasePrice": 900000})

    client.post(f"/api/agent/proposals/{proposal_id}/reject", json={})
    again = client.post(f"/api/agent/proposals/{proposal_id}/reject", json={})
    assert again.status_code == 400


# ---------------------------------------------------------------------------
# K8: plays
# ---------------------------------------------------------------------------

def test_list_plays_returns_id_and_label_only(client):
    resp = client.get("/api/agent/plays")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) > 0
    assert set(body[0]) == {"id", "label"}
    assert "screen" in {p["id"] for p in body}


def test_post_message_with_play_id_uses_the_canned_prompt(client, monkeypatch):
    deal = client.post("/api/deals", json={"name": "Test Deal"}).json()

    def fake_chat_with(provider_name, messages, tools, system):
        return ChatResult(text="Screened.", tool_calls=[], usage=Usage(1, 1), stop_reason="end_turn")

    monkeypatch.setattr(runner, "chat_with", fake_chat_with)

    resp = client.post(f"/api/agent/threads/{deal['id']}/messages", json={"playId": "screen"})
    assert resp.status_code == 200
    assert resp.json()["text"] == "Screened."

    thread = client.get(f"/api/agent/threads/{deal['id']}").json()
    assert "Screen this deal" in thread["messages"][0]["content"]


def test_post_message_unknown_play_id_is_400(client):
    deal = client.post("/api/deals", json={"name": "Test Deal"}).json()
    resp = client.post(f"/api/agent/threads/{deal['id']}/messages", json={"playId": "not-a-real-play"})
    assert resp.status_code == 400


def test_post_message_no_content_and_no_play_id_is_400(client):
    deal = client.post("/api/deals", json={"name": "Test Deal"}).json()
    resp = client.post(f"/api/agent/threads/{deal['id']}/messages", json={})
    assert resp.status_code == 400
