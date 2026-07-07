"""K4: the orchestration loop. One call in (a user message), one full JSON
turn out (non-streaming) — call the configured provider, execute READ tool
calls inline, accumulate WRITE tool results as AgentProposal rows (never
applied to Deal.inputs — see tools/write_tools.py), and repeat until the
provider returns plain text or a hard cap is hit. On any cap, stop cleanly
and say so; never loop silently.

Each new turn re-sends only prior user/assistant TEXT, not prior tool
calls/results (see AgentMessage's docstring in models.py) — the model
always re-verifies figures via a fresh tool call rather than trusting
stale output from earlier in the conversation, which is part of what makes
the anti-hallucination guarantee (K5) hold turn over turn, not just within
one turn."""

import json
import time
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AgentMessage, AgentProposal, AgentThread, AgentToolCall
from app.services.agent.providers import chat_with
from app.services.agent.providers.types import Message as ProviderMessage
from app.services.agent.tools.registry import ALL_TOOLS, to_tool_specs

MAX_TOOL_CALLS_PER_TURN = 25
MAX_COMPUTE_CALLS_PER_TURN = 15
MAX_WALL_CLOCK_SECONDS = 60

_COMPUTE_FAMILY = {"compute", "solve", "run_sensitivity", "run_tornado"}

SYSTEM_PROMPT = (
    "You are the Underwriting Agent inside a CRE deal-analysis dashboard. "
    "You have read/compute tools (get_deal, list_scenarios, get_scenario, "
    "compute, solve, run_sensitivity, run_tornado, get_market_context, "
    "list_comps, get_schema) that execute immediately, and write/propose "
    "tools (propose_input_changes, propose_scenario) that NEVER apply "
    "changes directly — they only create a proposal for the user to review "
    "and approve.\n\n"
    "The single most important rule: never state a number (an IRR, DSCR, "
    "price, rent, multiple, cap rate, or any other metric) unless it came "
    "from a tool call you made THIS turn. Cite which tool produced it. If "
    "you don't have a fresh number, call compute (or solve/run_sensitivity/"
    "run_tornado) to get one rather than estimating or recalling one from "
    "earlier in the conversation.\n\n"
    "If you want to recommend changing an input, call propose_input_changes "
    "or propose_scenario instead of just describing the change in text — "
    "the user approves or rejects your proposal; you never apply it "
    "yourself."
)


def _proposal_to_dict(p: AgentProposal) -> dict:
    return {
        "id": p.id,
        "kind": p.kind,
        "changes": p.changes,
        "rationale": p.rationale,
        "scenarioName": p.scenario_name,
        "preview": p.preview,
        "warnings": p.warnings,
        "status": p.status,
    }


def _load_history_as_provider_messages(db: Session, thread_id: str) -> list[ProviderMessage]:
    rows = db.execute(
        select(AgentMessage).where(AgentMessage.thread_id == thread_id).order_by(AgentMessage.created_at)
    ).scalars().all()
    return [ProviderMessage(role=m.role, content=m.content) for m in rows]


def run_turn(db: Session, thread: AgentThread, user_text: str) -> dict:
    start = time.monotonic()

    provider_messages = _load_history_as_provider_messages(db, thread.id)
    provider_messages.append(ProviderMessage(role="user", content=user_text))
    db.add(AgentMessage(thread_id=thread.id, role="user", content=user_text))

    assistant_message_id = str(uuid.uuid4())
    tool_specs = to_tool_specs()

    tool_call_count = 0
    compute_call_count = 0
    tool_call_log: list[dict] = []
    proposals: list[AgentProposal] = []
    stopped_reason: str | None = None
    final_text = ""

    while True:
        if time.monotonic() - start > MAX_WALL_CLOCK_SECONDS:
            stopped_reason = f"wall-clock limit ({MAX_WALL_CLOCK_SECONDS}s) reached"
            break
        if tool_call_count >= MAX_TOOL_CALLS_PER_TURN:
            stopped_reason = f"tool-call limit ({MAX_TOOL_CALLS_PER_TURN}) reached"
            break

        result = chat_with(thread.provider, provider_messages, tool_specs, SYSTEM_PROMPT)
        thread.total_input_tokens += result.usage.input_tokens
        thread.total_output_tokens += result.usage.output_tokens

        if result.stop_reason in ("unavailable", "error"):
            final_text = result.error or "The agent is currently unavailable."
            stopped_reason = result.stop_reason
            break

        if result.stop_reason == "end_turn":
            final_text = result.text
            break

        # stop_reason == "tool_use"
        provider_messages.append(
            ProviderMessage(role="assistant", content=result.text, tool_calls=result.tool_calls)
        )

        for call in result.tool_calls:
            if tool_call_count >= MAX_TOOL_CALLS_PER_TURN:
                stopped_reason = f"tool-call limit ({MAX_TOOL_CALLS_PER_TURN}) reached mid-batch"
                break

            tool_def = ALL_TOOLS.get(call.name)
            if tool_def is None:
                payload = {"error": f"Unknown tool '{call.name}'."}
                privilege = "unknown"
            elif tool_def.privilege == "read":
                privilege = "read"
                if call.name in _COMPUTE_FAMILY and compute_call_count >= MAX_COMPUTE_CALLS_PER_TURN:
                    payload = {
                        "error": f"compute-family tool-call limit ({MAX_COMPUTE_CALLS_PER_TURN}) "
                        "reached this turn."
                    }
                else:
                    if call.name in _COMPUTE_FAMILY:
                        compute_call_count += 1
                    try:
                        payload = tool_def.fn(db, **call.arguments)
                    except Exception as exc:  # noqa: BLE001 — a bad call becomes tool feedback, not a crash
                        payload = {"error": f"Tool call failed: {exc}"}
            else:  # write
                privilege = "write"
                try:
                    proposal = tool_def.fn(**call.arguments)
                    row = AgentProposal(
                        thread_id=thread.id,
                        deal_id=thread.deal_id,
                        tool_call_id=call.id,
                        kind=proposal.kind,
                        changes=proposal.changes,
                        rationale=proposal.rationale,
                        scenario_name=proposal.scenarioName,
                        preview=proposal.preview,
                        warnings=proposal.warnings,
                    )
                    db.add(row)
                    db.flush()
                    proposals.append(row)
                    payload = {
                        "proposalId": row.id,
                        "kind": row.kind,
                        "changes": row.changes,
                        "preview": row.preview,
                        "warnings": row.warnings,
                        "note": "Proposal created for user review — not applied.",
                    }
                except Exception as exc:  # noqa: BLE001 — same contract as the read branch
                    payload = {"error": f"Tool call failed: {exc}"}

            db.add(
                AgentToolCall(
                    thread_id=thread.id,
                    message_id=assistant_message_id,
                    tool_name=call.name,
                    privilege=privilege,
                    arguments=call.arguments,
                    result=payload,
                )
            )
            tool_call_log.append(
                {"name": call.name, "arguments": call.arguments, "result": payload, "privilege": privilege}
            )
            provider_messages.append(
                ProviderMessage(role="tool", tool_call_id=call.id, content=json.dumps(payload, default=str))
            )
            tool_call_count += 1

        if stopped_reason:
            break

    if stopped_reason and not final_text:
        final_text = (
            f"(Stopped early — {stopped_reason}.) I gathered information via tool calls but didn't "
            "finish forming a full response. Ask me to continue if you'd like more."
        )

    db.add(
        AgentMessage(
            id=assistant_message_id,
            thread_id=thread.id,
            role="assistant",
            content=final_text,
            tool_calls=tool_call_log,
            proposal_ids=[p.id for p in proposals],
            stopped_reason=stopped_reason,
        )
    )
    db.commit()

    return {
        "text": final_text,
        "toolCalls": tool_call_log,
        "proposals": [_proposal_to_dict(p) for p in proposals],
        "stoppedReason": stopped_reason,
    }
