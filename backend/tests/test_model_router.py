"""M3: per-task model routing — resolve_task's settings resolution,
chat_with_fallback's primary/fallback attempt logic, record_usage's
LlmUsageEvent persistence, and run_task's end-to-end chokepoint behavior
for classification/extraction. document_classifier.py's/llm_extraction.py's
own degrade-path shapes (unavailable/error) are re-verified here too, since
M3 changed HOW they reach a provider, not what they promise callers."""

import pytest
from sqlalchemy import select

from app.models import LlmUsageEvent
from app.services import document_classifier
from app.services import settings as settings_service
from app.services.agent import model_router
from app.services.agent.providers.types import ChatResult, Message, Usage
from app.services.extraction import llm_extraction


@pytest.fixture
def routing_overrides(monkeypatch):
    overrides: dict[str, str] = {}
    monkeypatch.setattr(
        settings_service, "resolve_setting", lambda key: (overrides.get(key, ""), "db")
    )
    return overrides


def _set_routing(overrides: dict, task: str, provider: str, model: str = "", fallback: str = "none"):
    overrides[f"routing.{task}.provider"] = provider
    overrides[f"routing.{task}.model"] = model
    overrides[f"routing.{task}.fallback"] = fallback


# ----------------------------------------------------------------------
# resolve_task
# ----------------------------------------------------------------------

def test_resolve_task_reads_the_three_settings(routing_overrides):
    _set_routing(routing_overrides, "classification", "anthropic", "claude-haiku-4-5-20251001", "openai")
    decision = model_router.resolve_task("classification")
    assert decision.provider == "anthropic"
    assert decision.model == "claude-haiku-4-5-20251001"
    assert decision.fallback == "openai"


def test_resolve_task_rejects_unknown_task(routing_overrides):
    with pytest.raises(ValueError):
        model_router.resolve_task("not-a-real-task")


# ----------------------------------------------------------------------
# chat_with_fallback
# ----------------------------------------------------------------------

def test_primary_success_never_attempts_fallback(monkeypatch, routing_overrides):
    calls = []

    def fake_chat_with(provider, messages, tools, system, model=None):
        calls.append(provider)
        return ChatResult(text="ok", tool_calls=[], usage=Usage(1, 1), stop_reason="end_turn")

    monkeypatch.setattr(model_router, "chat_with", fake_chat_with)
    result, provider_used, model_used = model_router.chat_with_fallback(
        "ollama", "llama3.1", "anthropic", [Message(role="user", content="hi")], [], "",
    )
    assert calls == ["ollama"]
    assert result.text == "ok"
    assert provider_used == "ollama"
    assert model_used == "llama3.1"


def test_primary_unavailable_triggers_fallback(monkeypatch, routing_overrides):
    calls = []

    def fake_chat_with(provider, messages, tools, system, model=None):
        calls.append(provider)
        if provider == "ollama":
            return ChatResult(text="", tool_calls=[], usage=Usage(), stop_reason="unavailable", error="no ollama")
        return ChatResult(text="from anthropic", tool_calls=[], usage=Usage(2, 2), stop_reason="end_turn")

    monkeypatch.setattr(model_router, "chat_with", fake_chat_with)
    result, provider_used, model_used = model_router.chat_with_fallback(
        "ollama", "llama3.1", "anthropic", [Message(role="user", content="hi")], [], "",
    )
    assert calls == ["ollama", "anthropic"]
    assert result.text == "from anthropic"
    assert provider_used == "anthropic"


def test_primary_error_also_triggers_fallback(monkeypatch, routing_overrides):
    def fake_chat_with(provider, messages, tools, system, model=None):
        if provider == "ollama":
            return ChatResult(text="", tool_calls=[], usage=Usage(), stop_reason="error", error="boom")
        return ChatResult(text="recovered", tool_calls=[], usage=Usage(1, 1), stop_reason="end_turn")

    monkeypatch.setattr(model_router, "chat_with", fake_chat_with)
    result, provider_used, _model_used = model_router.chat_with_fallback(
        "ollama", "", "anthropic", [Message(role="user", content="hi")], [], "",
    )
    assert result.text == "recovered"
    assert provider_used == "anthropic"


def test_both_unavailable_returns_the_fallback_failure(monkeypatch, routing_overrides):
    def fake_chat_with(provider, messages, tools, system, model=None):
        return ChatResult(text="", tool_calls=[], usage=Usage(), stop_reason="unavailable", error=f"{provider} down")

    monkeypatch.setattr(model_router, "chat_with", fake_chat_with)
    result, provider_used, _model_used = model_router.chat_with_fallback(
        "ollama", "", "anthropic", [Message(role="user", content="hi")], [], "",
    )
    assert result.stop_reason == "unavailable"
    assert provider_used == "anthropic"


def test_no_fallback_configured_never_attempts_one(monkeypatch, routing_overrides):
    calls = []

    def fake_chat_with(provider, messages, tools, system, model=None):
        calls.append(provider)
        return ChatResult(text="", tool_calls=[], usage=Usage(), stop_reason="unavailable")

    monkeypatch.setattr(model_router, "chat_with", fake_chat_with)
    model_router.chat_with_fallback("ollama", "", "none", [Message(role="user", content="hi")], [], "")
    assert calls == ["ollama"]


def test_fallback_same_as_primary_is_never_attempted_twice(monkeypatch, routing_overrides):
    calls = []

    def fake_chat_with(provider, messages, tools, system, model=None):
        calls.append(provider)
        return ChatResult(text="", tool_calls=[], usage=Usage(), stop_reason="unavailable")

    monkeypatch.setattr(model_router, "chat_with", fake_chat_with)
    model_router.chat_with_fallback("anthropic", "", "anthropic", [Message(role="user", content="hi")], [], "")
    assert calls == ["anthropic"]


# ----------------------------------------------------------------------
# record_usage
# ----------------------------------------------------------------------

def test_record_usage_writes_a_row_with_its_own_session():
    model_router.record_usage("classification", "ollama", "llama3.1", Usage(7, 3))
    with model_router.SessionLocal() as db:
        rows = db.execute(select(LlmUsageEvent)).scalars().all()
    assert len(rows) == 1
    assert rows[0].task == "classification"
    assert rows[0].provider == "ollama"
    assert rows[0].input_tokens == 7
    assert rows[0].output_tokens == 3


def test_record_usage_reuses_a_given_session_without_committing_itself():
    with model_router.SessionLocal() as db:
        model_router.record_usage("agent", "anthropic", "claude-sonnet-5", Usage(2, 2), db=db)
        # Visible within the SAME uncommitted session (pending, not yet
        # flushed to a separate connection) -- proves it reused `db` rather
        # than opening (and committing) its own.
        pending = [obj for obj in db.new if isinstance(obj, LlmUsageEvent)]
        assert len(pending) == 1
        db.rollback()  # never persisted -- the caller (runner.py) owns commit


def test_record_usage_logs_even_a_zero_token_unavailable_attempt():
    model_router.record_usage("extraction", "ollama", "", Usage(0, 0))
    with model_router.SessionLocal() as db:
        rows = db.execute(select(LlmUsageEvent)).scalars().all()
    assert len(rows) == 1
    assert rows[0].input_tokens == 0


# ----------------------------------------------------------------------
# run_task (the classification/extraction chokepoint)
# ----------------------------------------------------------------------

def test_run_task_records_usage_and_returns_provider_used(monkeypatch, routing_overrides):
    _set_routing(routing_overrides, "classification", "ollama")

    def fake_chat_with(provider, messages, tools, system, model=None):
        return ChatResult(text="ok", tool_calls=[], usage=Usage(5, 1), stop_reason="end_turn")

    monkeypatch.setattr(model_router, "chat_with", fake_chat_with)
    result, provider_used, _model_used = model_router.run_task(
        "classification", [Message(role="user", content="hi")], [], "",
    )
    assert result.text == "ok"
    assert provider_used == "ollama"
    with model_router.SessionLocal() as db:
        rows = db.execute(select(LlmUsageEvent)).scalars().all()
    assert len(rows) == 1
    assert rows[0].task == "classification"


# ----------------------------------------------------------------------
# document_classifier.py / llm_extraction.py: unchanged degrade-path
# shapes after the M3 refactor (they now reach a provider through
# model_router instead of constructing their own SDK client, but the
# CONTRACT with their own callers is unchanged).
# ----------------------------------------------------------------------

def test_classification_both_unavailable_falls_back_to_heuristic_none(routing_overrides):
    # No routing overrides set -> catalog defaults (ollama primary,
    # anthropic fallback) -> both unavailable in this isolated test env
    # (no real network, no keys) -> _llm_classify returns None, same as
    # the pre-M3 "no ANTHROPIC_API_KEY" contract.
    assert document_classifier._llm_classify("some real estate document text") is None


def test_extraction_both_unavailable_returns_none_result_with_note(routing_overrides):
    out = llm_extraction.extract_with_llm("offering_memorandum", "some document text", "doc.pdf", [])
    assert out["result"] is None
    assert "unavailable" in out["note"].lower()


def test_classification_empty_text_short_circuits_without_touching_router(monkeypatch):
    # No source text -> None before ever reaching model_router.run_task.
    calls = []
    monkeypatch.setattr(model_router, "run_task", lambda *a, **kw: calls.append(1))
    assert document_classifier._llm_classify("   ") is None
    assert calls == []
