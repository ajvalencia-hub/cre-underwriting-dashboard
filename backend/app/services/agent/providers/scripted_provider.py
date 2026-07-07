"""K11: a deterministic, network-free provider for the Playwright e2e gate.
Selected via AGENT_PROVIDER=scripted — never returned by accident (it's
just another entry in the factory's dict, only reachable if explicitly
configured, same opt-in shape as anthropic/openai needing their own key).

Behavior is keyed off the last user message's text and which tools have
already run this turn, and it reads REAL values out of prior tool results
rather than fabricating them — so it exercises the actual orchestration
loop, propose/approve flow, and K5 provenance checker exactly like a real
model would, except for one deliberate scenario (triggered by the word
"fabricate") that states an unsupported figure on purpose, to exercise the
anti-hallucination acceptance gate."""

import json

from app.services.agent.providers.types import ChatResult, Message, ToolCall, ToolSpec, Usage

# Deliberately NOT "target" — the "screen" play's own canned prompt says
# "solve-for-target checks", which would otherwise misroute every screen
# request onto the solve path.
_TARGET_KEYWORDS = ("gets me", "hits a", "hit a")


def _last_user_text(messages: list[Message]) -> str:
    for m in reversed(messages):
        if m.role == "user":
            return m.content
    return ""


def _tool_history(messages: list[Message]) -> list[tuple[str, dict]]:
    """[(tool_name, parsed_data), ...] in order, pairing each tool-role
    message with the assistant tool_call that requested it."""
    history: list[tuple[str, dict]] = []
    pending_names: list[str] = []
    for m in messages:
        if m.role == "assistant" and m.tool_calls:
            pending_names = [c.name for c in m.tool_calls]
        elif m.role == "tool":
            name = pending_names.pop(0) if pending_names else None
            try:
                data = json.loads(m.content).get("data", {})
            except (json.JSONDecodeError, AttributeError):
                data = {}
            if name:
                history.append((name, data))
    return history


def _last_result_for(history: list[tuple[str, dict]], name: str) -> dict | None:
    for tool_name, data in reversed(history):
        if tool_name == name:
            return data
    return None


def chat(messages: list[Message], tools: list[ToolSpec], system: str, model: str) -> ChatResult:
    last = messages[-1] if messages else None
    user_text = _last_user_text(messages).lower()
    history = _tool_history(messages)
    last_tool = history[-1] if history else None

    if "fabricate" in user_text or "hallucin" in user_text:
        return ChatResult(
            text="This deal has a strong DSCR of 1.9, comfortably above lender minimums.",
            tool_calls=[], usage=Usage(10, 10), stop_reason="end_turn",
        )

    if last is None or last.role == "user":
        return ChatResult(
            text="", tool_calls=[ToolCall(id="call_get_deal", name="get_deal", arguments={})],
            usage=Usage(10, 10), stop_reason="tool_use",
        )

    if last_tool and last_tool[0] == "get_deal":
        values = last_tool[1].get("inputs", {})
        if any(kw in user_text for kw in _TARGET_KEYWORDS):
            return ChatResult(
                text="",
                tool_calls=[ToolCall(
                    id="call_solve", name="solve",
                    arguments={
                        "values": values, "targetField": "exitCapRatePct", "targetMetric": "leveredIrr",
                        "targetValue": 0.15, "lowerBound": 0.03, "upperBound": 0.12,
                    },
                )],
                usage=Usage(10, 10), stop_reason="tool_use",
            )
        return ChatResult(
            text="",
            tool_calls=[ToolCall(id="call_compute", name="compute", arguments={"values": values})],
            usage=Usage(10, 10), stop_reason="tool_use",
        )

    if last_tool and last_tool[0] == "compute":
        irr = last_tool[1].get("outputs", {}).get("leveredIrr")
        summary = f"the levered IRR is {irr * 100:.1f}%" if isinstance(irr, (int, float)) else "no result"
        return ChatResult(
            text=f"Screened via compute: {summary}. Verdict: pursue.",
            tool_calls=[], usage=Usage(10, 10), stop_reason="end_turn",
        )

    if last_tool and last_tool[0] == "solve":
        field_value = last_tool[1].get("fieldValue")
        get_deal_values = (_last_result_for(history, "get_deal") or {}).get("inputs", {})
        if isinstance(field_value, (int, float)):
            return ChatResult(
                text="",
                tool_calls=[ToolCall(
                    id="call_propose", name="propose_input_changes",
                    arguments={
                        "currentValues": get_deal_values,
                        "changes": {"exitCapRatePct": field_value},
                        "rationale": "Hits a 15% levered IRR per the solve tool.",
                    },
                )],
                usage=Usage(10, 10), stop_reason="tool_use",
            )
        return ChatResult(
            text="Could not find an exit cap that hits that target within a reasonable range.",
            tool_calls=[], usage=Usage(10, 10), stop_reason="end_turn",
        )

    if last_tool and last_tool[0] == "propose_input_changes":
        exit_cap = last_tool[1].get("changes", {}).get("exitCapRatePct")
        pct = f"{exit_cap * 100:.2f}%" if isinstance(exit_cap, (int, float)) else "the solved value"
        return ChatResult(
            text=f"An exit cap rate of {pct} would hit a 15% levered IRR (via solve) — "
            "I've proposed this change for your review.",
            tool_calls=[], usage=Usage(10, 10), stop_reason="end_turn",
        )

    return ChatResult(text="ok", tool_calls=[], usage=Usage(1, 1), stop_reason="end_turn")
