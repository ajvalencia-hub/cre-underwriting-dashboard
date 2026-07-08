"""M2: Ollama (local) adapter — mocked at the httpx-client level (no live
Ollama instance required, matching this repo's existing "no live network
in tests" discipline for the Anthropic/OpenAI adapters). Covers: happy
path, tool-call parsing (arguments used directly, no json.loads; a
synthetic positional id is assigned since Ollama's native API has none),
connection failure -> unavailable, bad response -> error, factory
dispatch, and the /providers/health endpoint's reachability probe."""

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.services import settings as settings_service
from app.services.agent import runner
from app.services.agent.providers import chat_with, ollama_provider
from app.services.agent.providers.types import ChatResult, Message, ToolCall, ToolSpec, Usage

_TOOLS = [ToolSpec(name="get_deal", description="Fetch a deal.", parameters={"type": "object", "properties": {}})]


class _StubResponse:
    def __init__(self, status_code=200, payload=None, raises_on_status=False):
        self.status_code = status_code
        self._payload = payload or {}
        self._raises_on_status = raises_on_status

    def raise_for_status(self):
        if self._raises_on_status:
            raise RuntimeError(f"bad status: {self.status_code}")

    def json(self):
        return self._payload


@pytest.fixture
def settings_overrides(monkeypatch):
    overrides: dict[str, str] = {"ollamaBaseUrl": "http://localhost:11434", "ollamaAgentModel": "llama3.1"}
    monkeypatch.setattr(
        settings_service, "resolve_setting", lambda key: (overrides.get(key, ""), "db")
    )
    return overrides


def test_chat_text_only_response(monkeypatch, settings_overrides):
    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **kw: _StubResponse(payload={
            "message": {"role": "assistant", "content": "the DSCR is 1.4x"},
            "prompt_eval_count": 12, "eval_count": 6,
        }),
    )
    result = ollama_provider.chat([Message(role="user", content="what's the dscr")], _TOOLS, "system", "llama3.1")
    assert result.stop_reason == "end_turn"
    assert result.text == "the DSCR is 1.4x"
    assert result.tool_calls == []
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 6


def test_chat_tool_call_arguments_used_directly_no_json_loads(monkeypatch, settings_overrides):
    # Ollama's native API returns arguments as an already-parsed object, not
    # a JSON string (unlike OpenAI's Chat Completions API) -- a dict here,
    # not something requiring json.loads, proves the adapter doesn't
    # accidentally double-encode or choke on it.
    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **kw: _StubResponse(payload={
            "message": {
                "role": "assistant", "content": "",
                "tool_calls": [{"function": {"name": "get_deal", "arguments": {"dealId": "abc"}}}],
            },
            "prompt_eval_count": 10, "eval_count": 3,
        }),
    )
    result = ollama_provider.chat([Message(role="user", content="screen this deal")], _TOOLS, "system", "llama3.1")
    assert result.stop_reason == "tool_use"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "get_deal"
    assert result.tool_calls[0].arguments == {"dealId": "abc"}
    assert result.tool_calls[0].id  # synthesized, but must be non-empty


def test_multiple_tool_calls_get_distinct_synthesized_ids(monkeypatch, settings_overrides):
    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **kw: _StubResponse(payload={
            "message": {
                "role": "assistant", "content": "",
                "tool_calls": [
                    {"function": {"name": "get_deal", "arguments": {"dealId": "a"}}},
                    {"function": {"name": "get_deal", "arguments": {"dealId": "b"}}},
                ],
            },
        }),
    )
    result = ollama_provider.chat([Message(role="user", content="hi")], _TOOLS, "system", "llama3.1")
    ids = [c.id for c in result.tool_calls]
    assert len(ids) == len(set(ids)) == 2


def test_connection_error_degrades_to_unavailable(monkeypatch, settings_overrides):
    def _raise(*a, **kw):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", _raise)
    result = ollama_provider.chat([Message(role="user", content="hi")], [], "system", "llama3.1")
    assert result.stop_reason == "unavailable"
    assert result.error


def test_timeout_degrades_to_unavailable(monkeypatch, settings_overrides):
    def _raise(*a, **kw):
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(httpx, "post", _raise)
    result = ollama_provider.chat([Message(role="user", content="hi")], [], "system", "llama3.1")
    assert result.stop_reason == "unavailable"


def test_bad_status_is_error_not_unavailable(monkeypatch, settings_overrides):
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _StubResponse(status_code=404, raises_on_status=True))
    result = ollama_provider.chat([Message(role="user", content="hi")], [], "system", "llama3.1")
    assert result.stop_reason == "error"
    assert result.error


def test_message_round_trip_uses_ollama_native_shape(monkeypatch, settings_overrides):
    captured = {}

    def _capture_post(url, json, timeout):
        captured["json"] = json
        return _StubResponse(payload={"message": {"role": "assistant", "content": "done"}})

    monkeypatch.setattr(httpx, "post", _capture_post)
    messages = [
        Message(role="user", content="screen this deal"),
        Message(
            role="assistant",
            tool_calls=[ToolCall(id="call_0", name="get_deal", arguments={"dealId": "abc"})],
        ),
        Message(role="tool", tool_call_id="call_0", content='{"name": "Test Deal"}'),
    ]
    ollama_provider.chat(messages, _TOOLS, "system", "llama3.1")
    sent = captured["json"]["messages"]
    # Ollama's own tool_calls carry no id (unlike Anthropic/OpenAI) -- the
    # synthetic id is dropped when translating back into its wire format.
    assert sent[2]["tool_calls"] == [{"function": {"name": "get_deal", "arguments": {"dealId": "abc"}}}]
    assert sent[3]["role"] == "tool"
    assert sent[3]["content"] == '{"name": "Test Deal"}'


def test_tools_translated_to_openai_function_shape(monkeypatch, settings_overrides):
    captured = {}

    def _capture_post(url, json, timeout):
        captured["json"] = json
        return _StubResponse(payload={"message": {"content": "ok"}})

    monkeypatch.setattr(httpx, "post", _capture_post)
    ollama_provider.chat([Message(role="user", content="hi")], _TOOLS, "system", "llama3.1")
    assert captured["json"]["tools"][0]["type"] == "function"
    assert captured["json"]["tools"][0]["function"]["name"] == "get_deal"


# ----------------------------------------------------------------------
# Factory dispatch
# ----------------------------------------------------------------------

def test_factory_dispatches_to_ollama(monkeypatch, settings_overrides):
    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **kw: _StubResponse(payload={"message": {"content": "hi from ollama"}}),
    )
    result = chat_with("ollama", [Message(role="user", content="hi")], [], "system")
    assert result.text == "hi from ollama"


# ----------------------------------------------------------------------
# GET /api/agent/providers/health
# ----------------------------------------------------------------------

def test_health_endpoint_reports_ollama_reachable(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _StubResponse(status_code=200))
    client = TestClient(app)
    resp = client.get("/api/agent/providers/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ollama"]["reachable"] is True
    assert set(body) == {"anthropic", "openai", "ollama"}


def test_health_endpoint_reports_ollama_unreachable(monkeypatch):
    def _raise(*a, **kw):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", _raise)
    client = TestClient(app)
    resp = client.get("/api/agent/providers/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ollama"]["reachable"] is False
    assert body["ollama"]["detail"]


def test_health_endpoint_never_makes_a_live_call_for_cloud_providers(monkeypatch):
    # Anthropic/OpenAI health is key-presence only -- a real API ping would
    # burn money on every page load. Confirmed by NOT mocking any outbound
    # call for them and asserting the response still comes back cleanly.
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _StubResponse(status_code=200))
    client = TestClient(app)
    resp = client.get("/api/agent/providers/health")
    assert resp.json()["anthropic"]["detail"] is None
    assert resp.json()["openai"]["detail"] is None


# ----------------------------------------------------------------------
# K4 runner + K5 provenance: provider-agnostic by construction
# ----------------------------------------------------------------------

@pytest.fixture
def client():
    """Mirrors test_agent_router.py's isolated-engine client fixture —
    including NOT pointing settings_service.SessionLocal at this same
    StaticPool engine (see that file's fixture for why: a shared connection
    lets a second session's close() roll back this request's still-
    uncommitted AgentMessage insert mid-turn). conftest.py's autouse
    fixture already gives settings/model_router their own separate one."""
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


def test_runner_round_trip_identical_with_ollama_as_the_thread_provider(client, monkeypatch):
    """The K4 orchestration loop has exactly one provider-shaped line
    (chat_with(thread.provider, ...)) -- proven here by reusing the SAME
    stub shape the existing Anthropic/OpenAI-driven runner tests use,
    against a thread whose provider is "ollama". If runner.py branched on
    provider anywhere, this would need Ollama-specific setup; it doesn't."""
    deal = client.post("/api/deals", json={"name": "Ollama Test Deal"}).json()
    switch = client.put(f"/api/agent/threads/{deal['id']}/provider", json={"provider": "ollama"})
    assert switch.status_code == 200
    assert switch.json()["provider"] == "ollama"

    seen_providers = []

    def fake_chat_with(provider_name, messages, tools, system):
        seen_providers.append(provider_name)
        return ChatResult(
            text="Happy to help with this deal.", tool_calls=[], usage=Usage(4, 4), stop_reason="end_turn",
        )

    monkeypatch.setattr(runner, "chat_with", fake_chat_with)

    resp = client.post(f"/api/agent/threads/{deal['id']}/messages", json={"content": "hi"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "Happy to help with this deal."
    assert seen_providers == ["ollama"]
    # K5's provenance checker still ran (it's unconditional in run_turn) --
    # this plain, number-free response has nothing to flag.
    assert body["unverifiedClaims"] == []


def test_provenance_checker_is_provider_agnostic(client, monkeypatch):
    """K5's check_provenance() takes a plain str + a list of plain dicts --
    it has no provider-shaped input at all, so a hallucinated numeric claim
    from an "ollama"-provider turn is caught exactly the same way as from
    anthropic/openai (re-verifying the mechanism still gates, not just that
    the turn completes)."""
    deal = client.post("/api/deals", json={"name": "Ollama Hallucination Test", "inputs": {"purchasePrice": 1000000}}).json()
    client.put(f"/api/agent/threads/{deal['id']}/provider", json={"provider": "ollama"})

    def fake_chat_with(provider_name, messages, tools, system):
        # A confident-sounding number that was never pulled from any tool
        # call in this turn -- the provenance checker should flag it.
        return ChatResult(
            text="The purchase price is $9,999,999.", tool_calls=[], usage=Usage(2, 2), stop_reason="end_turn",
        )

    monkeypatch.setattr(runner, "chat_with", fake_chat_with)
    resp = client.post(f"/api/agent/threads/{deal['id']}/messages", json={"content": "what's the price"})
    assert resp.status_code == 200
    claims = resp.json()["unverifiedClaims"]
    assert len(claims) >= 1
