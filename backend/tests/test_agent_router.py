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
from app.services.agent.providers.types import ChatResult, Usage


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
