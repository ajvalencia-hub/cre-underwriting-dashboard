"""M5: cost estimation (app/services/cost.py), usage aggregation
(model_router.get_usage_summary), and the budget hard-stop's effect on the
K4 runner's write-tool gating (degrades to read-only, never a silent
no-op, never a 500)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.services import cost
from app.services import settings as settings_service
from app.services.agent import model_router, runner
from app.services.agent.providers.types import ChatResult, ToolCall, Usage

# ----------------------------------------------------------------------
# cost.estimate_cost
# ----------------------------------------------------------------------

def test_ollama_is_always_free():
    assert cost.estimate_cost("ollama", "llama3.1", Usage(1_000_000, 1_000_000)) == 0.0


def test_known_model_computes_expected_dollar_amount():
    # claude-haiku-4-5-20251001: $0.80/1M in, $4.00/1M out.
    result = cost.estimate_cost("anthropic", "claude-haiku-4-5-20251001", Usage(500_000, 250_000))
    assert result == pytest.approx(0.5 * 0.80 + 0.25 * 4.00)


def test_unknown_model_returns_none_not_zero():
    # "unknown cost" and "known zero cost" are different facts.
    assert cost.estimate_cost("anthropic", "not-a-real-model", Usage(100, 100)) is None


def test_zero_usage_on_a_known_model_is_zero_dollars():
    assert cost.estimate_cost("openai", "gpt-5.1", Usage(0, 0)) == 0.0


# ----------------------------------------------------------------------
# model_router.get_usage_summary
# ----------------------------------------------------------------------

@pytest.fixture
def routing_overrides(monkeypatch):
    overrides: dict[str, str] = {}
    monkeypatch.setattr(
        settings_service, "resolve_setting", lambda key: (overrides.get(key, ""), "db")
    )
    return overrides


def test_usage_summary_aggregates_by_task(routing_overrides):
    model_router.record_usage("classification", "ollama", "llama3.1", Usage(10, 5))
    model_router.record_usage("classification", "ollama", "llama3.1", Usage(20, 10))
    model_router.record_usage("agent", "anthropic", "claude-sonnet-5", Usage(100, 50))

    summary = model_router.get_usage_summary()
    assert summary["byTask"]["classification"]["calls"] == 2
    assert summary["byTask"]["classification"]["inputTokens"] == 30
    assert summary["byTask"]["agent"]["calls"] == 1
    assert summary["thisMonth"]["calls"] == 3


def test_usage_summary_tracks_unknown_cost_calls_separately(routing_overrides):
    model_router.record_usage("agent", "anthropic", "not-a-real-model", Usage(100, 100))
    summary = model_router.get_usage_summary()
    assert summary["thisMonth"]["unknownCostCalls"] == 1
    assert summary["thisMonth"]["costUsd"] == 0.0  # unknown, not counted as $0 spend


def test_usage_summary_scoped_to_deal_when_requested(routing_overrides):
    model_router.record_usage("agent", "ollama", "llama3.1", Usage(1, 1), deal_id="deal-a")
    model_router.record_usage("agent", "ollama", "llama3.1", Usage(2, 2), deal_id="deal-b")

    summary = model_router.get_usage_summary(deal_id="deal-a")
    assert summary["thisDeal"]["calls"] == 1
    assert summary["thisDeal"]["inputTokens"] == 1
    assert summary["thisMonth"]["calls"] == 2  # global total, unaffected by the deal filter


def test_no_budget_set_never_warns_or_stops(routing_overrides):
    routing_overrides["monthlyBudgetUsd"] = "0"
    model_router.record_usage("agent", "anthropic", "claude-sonnet-5", Usage(1_000_000, 1_000_000))
    summary = model_router.get_usage_summary()
    assert summary["budget"]["monthlyBudgetUsd"] is None
    assert summary["budget"]["softWarn"] is False
    assert summary["budget"]["hardStopped"] is False


def test_budget_soft_warn_below_hard_stop(routing_overrides):
    routing_overrides["monthlyBudgetUsd"] = "10"
    # claude-sonnet-5: $3/1M in, $15/1M out -> 2.4M in tokens alone = $7.20 (72% of $10)
    model_router.record_usage("agent", "anthropic", "claude-sonnet-5", Usage(2_800_000, 0))
    summary = model_router.get_usage_summary()
    assert summary["budget"]["spentUsd"] == pytest.approx(8.4)
    assert summary["budget"]["softWarn"] is True
    assert summary["budget"]["hardStopped"] is False


def test_budget_hard_stop_once_spend_meets_the_cap(routing_overrides):
    routing_overrides["monthlyBudgetUsd"] = "1"
    model_router.record_usage("agent", "anthropic", "claude-sonnet-5", Usage(1_000_000, 0))  # $3
    summary = model_router.get_usage_summary()
    assert summary["budget"]["hardStopped"] is True
    assert model_router.is_budget_hard_stopped() is True


# ----------------------------------------------------------------------
# Runner integration: hard-stop degrades write tools, never silently
# ----------------------------------------------------------------------

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


def test_hard_stopped_budget_skips_proposal_creation_with_a_clear_message(
    client, monkeypatch, routing_overrides
):
    routing_overrides["monthlyBudgetUsd"] = "0.01"
    monkeypatch.setattr(
        model_router, "is_budget_hard_stopped", lambda: True,
    )

    results = iter([
        ChatResult(
            text="",
            tool_calls=[ToolCall(
                id="c1", name="propose_input_changes",
                arguments={"currentValues": {}, "changes": {"purchasePrice": 900000}, "rationale": "test"},
            )],
            usage=Usage(1, 1), stop_reason="tool_use",
        ),
        ChatResult(text="Noted.", tool_calls=[], usage=Usage(1, 1), stop_reason="end_turn"),
    ])

    def fake_chat_with(provider_name, messages, tools, system):
        return next(results)

    monkeypatch.setattr(runner, "chat_with", fake_chat_with)
    deal = client.post("/api/deals", json={"name": "Budget Test Deal"}).json()
    resp = client.post(f"/api/agent/threads/{deal['id']}/messages", json={"content": "propose a change"})

    assert resp.status_code == 200  # never a 500 -- degrades cleanly
    body = resp.json()
    assert body["proposals"] == []  # nothing was created
    tool_call = body["toolCalls"][0]
    assert "budget" in tool_call["result"]["error"].lower()


def test_under_budget_still_creates_proposals_normally(client, monkeypatch, routing_overrides):
    routing_overrides["monthlyBudgetUsd"] = "0"  # no budget configured

    results = iter([
        ChatResult(
            text="",
            tool_calls=[ToolCall(
                id="c1", name="propose_input_changes",
                arguments={"currentValues": {}, "changes": {"purchasePrice": 900000}, "rationale": "test"},
            )],
            usage=Usage(1, 1), stop_reason="tool_use",
        ),
        ChatResult(text="Proposed.", tool_calls=[], usage=Usage(1, 1), stop_reason="end_turn"),
    ])

    def fake_chat_with(provider_name, messages, tools, system):
        return next(results)

    monkeypatch.setattr(runner, "chat_with", fake_chat_with)
    deal = client.post("/api/deals", json={"name": "Under Budget Deal"}).json()
    resp = client.post(f"/api/agent/threads/{deal['id']}/messages", json={"content": "propose a change"})
    assert resp.status_code == 200
    assert len(resp.json()["proposals"]) == 1


# ----------------------------------------------------------------------
# GET /api/settings/usage
# ----------------------------------------------------------------------

def test_usage_endpoint_returns_the_expected_shape(client, routing_overrides):
    resp = client.get("/api/settings/usage")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"thisDeal", "today", "thisMonth", "byTask", "budget"}
    assert body["thisDeal"] is None  # no dealId query param given
    assert set(body["byTask"]) == set(model_router.TASKS)


def test_usage_endpoint_registered_before_the_key_route(client):
    # A regression guard for the /usage-vs-/{key} route-ordering trap noted
    # in routers/settings.py -- "usage" must never be treated as an unknown
    # setting key (which would 404).
    resp = client.get("/api/settings/usage")
    assert resp.status_code == 200
