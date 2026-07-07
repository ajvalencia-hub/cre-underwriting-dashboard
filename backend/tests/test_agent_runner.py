"""K4: the orchestration loop — scripted-provider-mock turns (no real network,
same discipline as test_agent_providers.py), covering: a compute-call-then-
text happy path, tool-cap enforcement, compute-family-cap enforcement,
proposal accumulation without ever touching Deal.inputs, unknown-tool
recovery, provider-unavailable/error handling, and thread/message
persistence round-trips."""

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AgentMessage, AgentProposal, AgentThread, Deal
from app.services.agent import runner
from app.services.agent.providers.types import ChatResult, ToolCall, Usage

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def analytic() -> dict:
    return json.loads((FIXTURES / "analytic_acquisition.json").read_text())


@pytest.fixture
def deal(db, analytic):
    d = Deal(name="Test Deal", inputs=analytic)
    db.add(d)
    db.commit()
    return d


@pytest.fixture
def thread(db, deal):
    t = AgentThread(deal_id=deal.id, provider="anthropic")
    db.add(t)
    db.commit()
    return t


class _ScriptedProvider:
    """Pops one ChatResult per chat_with() call, in order. Raises if the
    runner calls it more times than the test scripted for — that itself is
    a meaningful assertion (the loop shouldn't call the provider more than
    expected for a given scenario)."""

    def __init__(self, results: list[ChatResult]):
        self._results = list(results)
        self.calls: list[dict] = []

    def __call__(self, provider_name, messages, tools, system):
        self.calls.append({"provider": provider_name, "messages": messages, "tools": tools})
        if not self._results:
            raise AssertionError("provider called more times than scripted")
        return self._results.pop(0)


def _install(monkeypatch, results: list[ChatResult]) -> _ScriptedProvider:
    scripted = _ScriptedProvider(results)
    monkeypatch.setattr(runner, "chat_with", scripted)
    return scripted


# ---------------------------------------------------------------------------
# Happy path: one tool call, then text
# ---------------------------------------------------------------------------

def test_compute_call_then_text_happy_path(db, thread, analytic, monkeypatch):
    scripted = _install(monkeypatch, [
        ChatResult(
            text="", tool_calls=[ToolCall(id="c1", name="compute", arguments={"values": analytic})],
            usage=Usage(10, 5), stop_reason="tool_use",
        ),
        ChatResult(text="The levered IRR is 11.6%.", tool_calls=[], usage=Usage(8, 4), stop_reason="end_turn"),
    ])

    out = runner.run_turn(db, thread, "What's the levered IRR?")

    assert out["text"] == "The levered IRR is 11.6%."
    assert out["stoppedReason"] is None
    assert len(out["toolCalls"]) == 1
    assert out["toolCalls"][0]["name"] == "compute"
    assert "leveredIrr" in out["toolCalls"][0]["result"]["outputs"]
    assert len(scripted.calls) == 2

    db.refresh(thread)
    assert thread.total_input_tokens == 18
    assert thread.total_output_tokens == 9


def test_thread_and_message_persistence_round_trip(db, thread, monkeypatch):
    _install(monkeypatch, [
        ChatResult(text="Hello!", tool_calls=[], usage=Usage(3, 2), stop_reason="end_turn"),
    ])
    runner.run_turn(db, thread, "hi there")

    messages = db.execute(
        select(AgentMessage).where(AgentMessage.thread_id == thread.id).order_by(AgentMessage.created_at)
    ).scalars().all()
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "hi there"
    assert messages[1].role == "assistant"
    assert messages[1].content == "Hello!"


def test_second_turn_does_not_replay_tool_calls_to_provider(db, thread, analytic, monkeypatch):
    # First turn: a tool call then text.
    _install(monkeypatch, [
        ChatResult(
            text="", tool_calls=[ToolCall(id="c1", name="compute", arguments={"values": analytic})],
            usage=Usage(1, 1), stop_reason="tool_use",
        ),
        ChatResult(text="IRR is 11.6%.", tool_calls=[], usage=Usage(1, 1), stop_reason="end_turn"),
    ])
    runner.run_turn(db, thread, "what's the irr")

    # Second turn: the provider should only see plain user/assistant text
    # (2 prior messages), never a tool_use/tool_result block from turn 1.
    scripted = _install(monkeypatch, [
        ChatResult(text="Sure, anything else?", tool_calls=[], usage=Usage(1, 1), stop_reason="end_turn"),
    ])
    runner.run_turn(db, thread, "thanks")

    sent_messages = scripted.calls[0]["messages"]
    assert len(sent_messages) == 3  # 2 prior (user+assistant) + this turn's new user message
    assert all(m.tool_calls == [] for m in sent_messages)
    assert sent_messages[0].content == "what's the irr"
    assert sent_messages[1].content == "IRR is 11.6%."
    assert sent_messages[2].content == "thanks"


# ---------------------------------------------------------------------------
# Cap enforcement
# ---------------------------------------------------------------------------

def test_tool_call_cap_stops_cleanly(db, thread, analytic, monkeypatch):
    monkeypatch.setattr(runner, "MAX_TOOL_CALLS_PER_TURN", 3)
    # The model keeps calling get_schema forever; the loop must stop at the cap.
    infinite_tool_use = ChatResult(
        text="", tool_calls=[ToolCall(id="c", name="get_schema", arguments={})],
        usage=Usage(1, 1), stop_reason="tool_use",
    )
    _install(monkeypatch, [infinite_tool_use] * 10)

    out = runner.run_turn(db, thread, "loop forever")

    assert out["stoppedReason"] is not None
    assert "tool-call limit" in out["stoppedReason"]
    assert len(out["toolCalls"]) <= 3
    assert "Stopped early" in out["text"]


def test_compute_family_cap_returns_error_result_not_crash(db, thread, analytic, monkeypatch):
    monkeypatch.setattr(runner, "MAX_COMPUTE_CALLS_PER_TURN", 2)
    batch = ChatResult(
        text="",
        tool_calls=[
            ToolCall(id="c1", name="compute", arguments={"values": analytic}),
            ToolCall(id="c2", name="compute", arguments={"values": analytic}),
            ToolCall(id="c3", name="compute", arguments={"values": analytic}),
        ],
        usage=Usage(1, 1), stop_reason="tool_use",
    )
    _install(monkeypatch, [batch, ChatResult(text="done", tool_calls=[], usage=Usage(1, 1), stop_reason="end_turn")])

    out = runner.run_turn(db, thread, "compute it three times")

    results = [tc["result"] for tc in out["toolCalls"]]
    assert sum(1 for r in results if "error" in r and "compute-family" in r["error"]) == 1
    assert sum(1 for r in results if "outputs" in r) == 2


# ---------------------------------------------------------------------------
# Proposals never touch the DB
# ---------------------------------------------------------------------------

def test_proposal_accumulates_without_mutating_deal(db, thread, deal, analytic, monkeypatch):
    _install(monkeypatch, [
        ChatResult(
            text="",
            tool_calls=[ToolCall(
                id="c1", name="propose_input_changes",
                arguments={"currentValues": analytic, "changes": {"exitCapRatePct": 0.075}, "rationale": "test"},
            )],
            usage=Usage(1, 1), stop_reason="tool_use",
        ),
        ChatResult(text="Proposed a lower exit cap.", tool_calls=[], usage=Usage(1, 1), stop_reason="end_turn"),
    ])

    out = runner.run_turn(db, thread, "propose a lower exit cap")

    assert len(out["proposals"]) == 1
    assert out["proposals"][0]["kind"] == "input_changes"
    assert out["proposals"][0]["status"] == "pending"

    db.refresh(deal)
    assert deal.inputs["exitCapRatePct"] == 0.08  # untouched — still the original value

    rows = db.execute(select(AgentProposal).where(AgentProposal.thread_id == thread.id)).scalars().all()
    assert len(rows) == 1
    assert rows[0].changes == {"exitCapRatePct": 0.075}


# ---------------------------------------------------------------------------
# Recovery paths
# ---------------------------------------------------------------------------

def test_unknown_tool_name_recovers_instead_of_crashing(db, thread, monkeypatch):
    _install(monkeypatch, [
        ChatResult(
            text="", tool_calls=[ToolCall(id="c1", name="not_a_real_tool", arguments={})],
            usage=Usage(1, 1), stop_reason="tool_use",
        ),
        ChatResult(text="Sorry, let me try something else.", tool_calls=[], usage=Usage(1, 1), stop_reason="end_turn"),
    ])

    out = runner.run_turn(db, thread, "do the thing")

    assert out["text"] == "Sorry, let me try something else."
    assert "error" in out["toolCalls"][0]["result"]
    assert out["toolCalls"][0]["privilege"] == "unknown"


def test_provider_unavailable_does_not_crash(db, thread, monkeypatch):
    _install(monkeypatch, [
        ChatResult(text="", tool_calls=[], usage=Usage(0, 0), stop_reason="unavailable", error="no API key set"),
    ])

    out = runner.run_turn(db, thread, "hi")

    assert out["text"] == "no API key set"
    assert out["stoppedReason"] == "unavailable"


def test_provider_error_does_not_crash(db, thread, monkeypatch):
    _install(monkeypatch, [
        ChatResult(text="", tool_calls=[], usage=Usage(0, 0), stop_reason="error", error="network timeout"),
    ])

    out = runner.run_turn(db, thread, "hi")

    assert out["text"] == "network timeout"
    assert out["stoppedReason"] == "error"


# ---------------------------------------------------------------------------
# K5 integration: unverified claims flow through to the response + persisted row
# ---------------------------------------------------------------------------

def test_fabricated_figure_surfaces_as_unverified_claim(db, thread, analytic, monkeypatch):
    _install(monkeypatch, [
        ChatResult(
            text="", tool_calls=[ToolCall(id="c1", name="compute", arguments={"values": analytic})],
            usage=Usage(1, 1), stop_reason="tool_use",
        ),
        ChatResult(
            text="This deal has a strong DSCR of 1.9, well above lender minimums.",
            tool_calls=[], usage=Usage(1, 1), stop_reason="end_turn",
        ),
    ])

    out = runner.run_turn(db, thread, "how does this deal look?")

    assert len(out["unverifiedClaims"]) == 1
    assert out["unverifiedClaims"][0]["value"] == 1.9

    assistant_row = db.execute(
        select(AgentMessage).where(AgentMessage.thread_id == thread.id, AgentMessage.role == "assistant")
    ).scalars().one()
    assert assistant_row.unverified_claims == out["unverifiedClaims"]


def test_grounded_figures_produce_no_unverified_claims(db, thread, analytic, monkeypatch):
    _install(monkeypatch, [
        ChatResult(
            text="", tool_calls=[ToolCall(id="c1", name="compute", arguments={"values": analytic})],
            usage=Usage(1, 1), stop_reason="tool_use",
        ),
        ChatResult(text="The levered IRR is 11.6%.", tool_calls=[], usage=Usage(1, 1), stop_reason="end_turn"),
    ])

    out = runner.run_turn(db, thread, "what's the irr?")

    assert out["unverifiedClaims"] == []


def test_unavailable_error_text_is_not_run_through_provenance_check(db, thread, monkeypatch):
    _install(monkeypatch, [
        ChatResult(text="", tool_calls=[], usage=Usage(0, 0), stop_reason="unavailable", error="no API key set"),
    ])

    out = runner.run_turn(db, thread, "hi")

    assert out["unverifiedClaims"] == []
