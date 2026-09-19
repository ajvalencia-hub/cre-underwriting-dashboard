"""The agent's adaptations to the later-items architecture: the IC lock and
input validation gate proposal approval, invalid inputs come back as tool
errors (never a 500), every route declares its api_models response model,
and the read tools work on the target's schema/engine (new inputs/outputs)."""

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.main import app
from app.models import AgentProposal, DealSnapshot
from app.services.agent import runner
from app.services.agent.providers.types import ChatResult, ToolCall, Usage
from app.services.agent.tools import read_tools, write_tools

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def analytic() -> dict:
    data = json.loads((FIXTURES / "analytic_acquisition.json").read_text(encoding="utf-8"))
    data.pop("_comment", None)
    return data


def _stub_sequence(monkeypatch, results: list[ChatResult]) -> None:
    it = iter(results)
    monkeypatch.setattr(runner, "chat_with", lambda *_args: next(it))


def _turn_with_tool(client, monkeypatch, deal_id: str, name: str, arguments: dict) -> dict:
    _stub_sequence(monkeypatch, [
        ChatResult(
            text="", tool_calls=[ToolCall(id="c1", name=name, arguments=arguments)],
            usage=Usage(1, 1), stop_reason="tool_use",
        ),
        ChatResult(text="Done.", tool_calls=[], usage=Usage(1, 1), stop_reason="end_turn"),
    ])
    resp = client.post(f"/api/agent/threads/{deal_id}/messages", json={"content": "go"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _propose(client, monkeypatch, deal_id: str, changes: dict) -> str:
    turn = _turn_with_tool(
        client, monkeypatch, deal_id, "propose_input_changes",
        {"currentValues": {}, "changes": changes, "rationale": "test"},
    )
    return turn["proposals"][0]["id"]


def _snapshots(client, deal_id: str) -> list[DealSnapshot]:
    with client._session() as db:
        return list(db.execute(select(DealSnapshot).where(DealSnapshot.deal_id == deal_id)).scalars())


# ---------------------------------------------------------------------------
# approve: IC lock
# ---------------------------------------------------------------------------

def test_approve_on_an_ic_locked_deal_is_409_and_writes_nothing(client, monkeypatch, analytic):
    deal_id = client.post("/api/deals", json={"name": "Locked", "inputs": analytic}).json()["id"]
    proposal_id = _propose(client, monkeypatch, deal_id, {"purchasePrice": 1_100_000})
    submitted = client.post(
        f"/api/deals/{deal_id}/ic/events", json={"kind": "submit", "actor": "Ana", "comment": "Base"}
    )
    assert submitted.status_code == 200, submitted.text
    snapshots_before = len(_snapshots(client, deal_id))

    resp = client.post(f"/api/agent/proposals/{proposal_id}/approve", json={})

    assert resp.status_code == 409
    assert "locked" in resp.json()["detail"]
    deal = client.get(f"/api/deals/{deal_id}").json()
    assert deal["inputs"]["purchasePrice"] == analytic["purchasePrice"]
    snapshots = _snapshots(client, deal_id)
    assert len(snapshots) == snapshots_before
    assert not any(s.kind == "agent" for s in snapshots)
    with client._session() as db:
        assert db.get(AgentProposal, proposal_id).status == "pending"


def test_approve_after_reopen_applies(client, monkeypatch, analytic):
    deal_id = client.post("/api/deals", json={"name": "Reopened", "inputs": analytic}).json()["id"]
    proposal_id = _propose(client, monkeypatch, deal_id, {"purchasePrice": 1_100_000})
    client.post(f"/api/deals/{deal_id}/ic/events", json={"kind": "submit", "actor": "Ana", "comment": "Base"})
    assert client.post(f"/api/agent/proposals/{proposal_id}/approve", json={}).status_code == 409
    reopened = client.post(
        f"/api/deals/{deal_id}/ic/events", json={"kind": "reopen", "actor": "Ana", "comment": "Rework"}
    )
    assert reopened.status_code == 200, reopened.text

    resp = client.post(f"/api/agent/proposals/{proposal_id}/approve", json={})

    assert resp.status_code == 200
    assert resp.json()["deal"]["inputs"]["purchasePrice"] == 1_100_000
    assert any(s.kind == "agent" for s in _snapshots(client, deal_id))


def test_approve_non_underwriting_change_on_a_locked_deal_is_allowed(client, monkeypatch, analytic):
    """check_input_change ignores UNLOCKED_KEYS, so an approval that changes
    nothing the IC signed off on goes through (same rule as PUT /api/deals)."""
    deal_id = client.post("/api/deals", json={"name": "Same", "inputs": analytic}).json()["id"]
    proposal_id = _propose(client, monkeypatch, deal_id, {"purchasePrice": analytic["purchasePrice"]})
    client.post(f"/api/deals/{deal_id}/ic/events", json={"kind": "submit", "actor": "Ana", "comment": "Base"})

    resp = client.post(f"/api/agent/proposals/{proposal_id}/approve", json={})

    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# approve / tools: input validation
# ---------------------------------------------------------------------------

def test_approve_with_invalid_override_is_422_and_writes_nothing(client, monkeypatch, analytic):
    deal_id = client.post("/api/deals", json={"name": "Bad override", "inputs": analytic}).json()["id"]
    proposal_id = _propose(client, monkeypatch, deal_id, {"purchasePrice": 1_100_000})

    resp = client.post(
        f"/api/agent/proposals/{proposal_id}/approve",
        json={"overrideChanges": {"purchasePrice": "about a million"}},
    )

    assert resp.status_code == 422
    body = resp.json()
    assert "purchasePrice" in body["detail"]
    assert body["missing"]
    assert client.get(f"/api/deals/{deal_id}").json()["inputs"]["purchasePrice"] == analytic["purchasePrice"]
    assert not any(s.kind == "agent" for s in _snapshots(client, deal_id))


def test_propose_with_invalid_table_cell_is_a_tool_error_not_a_proposal(client, monkeypatch, analytic):
    deal_id = client.post("/api/deals", json={"name": "Bad table", "inputs": analytic}).json()["id"]
    turn = _turn_with_tool(
        client, monkeypatch, deal_id, "propose_input_changes",
        {
            "currentValues": analytic,
            "changes": {"forwardCurve": [{"month": "soon", "indexPct": 0.04}]},
            "rationale": "curve",
        },
    )

    assert turn["proposals"] == []
    result = turn["toolCalls"][0]["result"]
    assert "Invalid input values" in result["error"]
    assert any("forwardCurve" in e for e in result["invalid"])
    with client._session() as db:
        assert db.execute(select(AgentProposal)).first() is None


def test_propose_with_non_dict_changes_is_a_tool_error(client, monkeypatch, analytic):
    deal_id = client.post("/api/deals", json={"name": "Junk", "inputs": analytic}).json()["id"]
    turn = _turn_with_tool(
        client, monkeypatch, deal_id, "propose_input_changes",
        {"currentValues": analytic, "changes": ["purchasePrice"], "rationale": "x"},
    )
    assert turn["proposals"] == []
    assert "error" in turn["toolCalls"][0]["result"]


def test_write_tools_drop_non_numeric_multiple_and_years_fields():
    proposal = write_tools.propose_input_changes({}, {"holdPeriodYears": "five"}, "x")
    assert "holdPeriodYears" not in proposal.changes
    assert any("holdPeriodYears" in w for w in proposal.warnings)


def test_compute_with_invalid_value_is_a_tool_error(analytic):
    result = read_tools.compute(None, {**analytic, "purchasePrice": "lots"})  # type: ignore[arg-type]
    assert "error" in result
    assert any("purchasePrice" in m for m in result["missing"])


def test_sensitivity_with_invalid_base_values_is_one_tool_error(analytic):
    result = read_tools.run_sensitivity(
        None,  # type: ignore[arg-type]
        {**analytic, "purchasePrice": "lots"},
        [{"fieldId": "exitCapRatePct", "values": [0.07, 0.08]}],
        ["leveredIrr"],
    )
    assert "error" in result
    assert "points" not in result


def test_tornado_and_solve_with_invalid_values_are_tool_errors(analytic):
    bad = {**analytic, "purchasePrice": "lots"}
    assert "error" in read_tools.run_tornado(None, bad)  # type: ignore[arg-type]
    assert "error" in read_tools.solve(None, "exitCapRatePct", "leveredIrr", 0.1, values=bad)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# target schema / engine
# ---------------------------------------------------------------------------

def test_get_schema_lists_target_inputs_and_outputs():
    ids = {f["id"] for f in read_tools.get_schema(None)["fields"]}  # type: ignore[arg-type]
    assert {"exitNoiBasis", "loanTermYears", "prepaymentCost", "goingInDebtYield"} <= ids


def test_compute_returns_target_outputs(analytic):
    result = read_tools.compute(None, analytic)  # type: ignore[arg-type]
    assert "error" not in result
    assert "goingInDebtYield" in result["outputs"]
    assert result["outputs"]["leveredIrr"] is not None


# ---------------------------------------------------------------------------
# api contract
# ---------------------------------------------------------------------------

def test_every_agent_route_declares_a_response_model():
    spec = app.openapi()
    agent_paths = {p: ops for p, ops in spec["paths"].items() if p.startswith("/api/agent/")}
    assert len(agent_paths) == 7
    for path, ops in agent_paths.items():
        for method, op in ops.items():
            schema = op["responses"]["200"]["content"]["application/json"]["schema"]
            assert schema, f"{method.upper()} {path} has no response schema"
            assert schema != {}, f"{method.upper()} {path} has an untyped response"


def test_thread_payload_matches_the_declared_model(client, monkeypatch, analytic):
    deal_id = client.post("/api/deals", json={"name": "Shape", "inputs": analytic}).json()["id"]
    _propose(client, monkeypatch, deal_id, {"purchasePrice": 1_050_000})
    thread = client.get(f"/api/agent/threads/{deal_id}").json()
    assert set(thread) >= {
        "id", "dealId", "provider", "totalInputTokens", "totalOutputTokens", "messages", "proposals",
    }
    user, assistant = thread["messages"]
    assert user["toolCalls"] == [] and assistant["toolCalls"][0]["privilege"] == "write"
    assert thread["proposals"][0]["createdAt"]


def test_approve_404s_when_the_deal_is_gone(client):
    """Approving a proposal whose deal was deleted is a 404, not a 500."""
    with client._session() as db:
        db.add(AgentProposal(
            id="p1", thread_id="t1", deal_id="missing-deal", tool_call_id="c1",
            kind="input_changes", changes={}, rationale="", warnings=[],
        ))
        db.commit()
    assert client.post("/api/agent/proposals/p1/approve", json={}).status_code == 404
