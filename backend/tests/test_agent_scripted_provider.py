"""K11: unit-level check of the scripted provider's script logic in
isolation — fast feedback before relying on it through the full Playwright
stack. Exercises the same message-history shapes the real runner builds."""

import json

from app.services.agent.providers import scripted_provider
from app.services.agent.providers.types import Message, ToolCall


def _tool_message(tool_call_id: str, data: dict) -> Message:
    return Message(
        role="tool", tool_call_id=tool_call_id,
        content=json.dumps({"_note": "data", "data": data}),
    )


def test_fresh_screen_turn_starts_with_get_deal():
    messages = [Message(role="user", content="Screen this deal")]
    result = scripted_provider.chat(messages, [], "system", "scripted-v1")
    assert result.stop_reason == "tool_use"
    assert result.tool_calls[0].name == "get_deal"
    assert result.tool_calls[0].arguments == {}


def test_after_get_deal_screen_intent_calls_compute():
    messages = [
        Message(role="user", content="Screen this deal"),
        Message(role="assistant", tool_calls=[ToolCall(id="c1", name="get_deal", arguments={})]),
        _tool_message("c1", {"id": "d1", "inputs": {"purchasePrice": 1000000}}),
    ]
    result = scripted_provider.chat(messages, [], "system", "scripted-v1")
    assert result.stop_reason == "tool_use"
    assert result.tool_calls[0].name == "compute"
    assert result.tool_calls[0].arguments["values"] == {"purchasePrice": 1000000}


def test_after_compute_ends_turn_with_irr_cited():
    messages = [
        Message(role="user", content="Screen this deal"),
        Message(role="assistant", tool_calls=[ToolCall(id="c1", name="get_deal", arguments={})]),
        _tool_message("c1", {"inputs": {}}),
        Message(role="assistant", tool_calls=[ToolCall(id="c2", name="compute", arguments={"values": {}})]),
        _tool_message("c2", {"outputs": {"leveredIrr": 0.115718}}),
    ]
    result = scripted_provider.chat(messages, [], "system", "scripted-v1")
    assert result.stop_reason == "end_turn"
    assert "11.6%" in result.text


def test_target_intent_calls_solve_after_get_deal():
    messages = [
        Message(role="user", content="What exit cap gets me to a 15% IRR?"),
        Message(role="assistant", tool_calls=[ToolCall(id="c1", name="get_deal", arguments={})]),
        _tool_message("c1", {"inputs": {"exitCapRatePct": 0.08}}),
    ]
    result = scripted_provider.chat(messages, [], "system", "scripted-v1")
    assert result.stop_reason == "tool_use"
    assert result.tool_calls[0].name == "solve"
    assert result.tool_calls[0].arguments["targetMetric"] == "leveredIrr"
    assert result.tool_calls[0].arguments["targetValue"] == 0.15


def test_after_solve_proposes_the_change():
    messages = [
        Message(role="user", content="What exit cap gets me to a 15% IRR?"),
        Message(role="assistant", tool_calls=[ToolCall(id="c1", name="get_deal", arguments={})]),
        _tool_message("c1", {"inputs": {"exitCapRatePct": 0.08}}),
        Message(role="assistant", tool_calls=[ToolCall(id="c2", name="solve", arguments={})]),
        _tool_message("c2", {"fieldValue": 0.079, "metricValue": 0.15}),
    ]
    result = scripted_provider.chat(messages, [], "system", "scripted-v1")
    assert result.stop_reason == "tool_use"
    assert result.tool_calls[0].name == "propose_input_changes"
    assert result.tool_calls[0].arguments["changes"] == {"exitCapRatePct": 0.079}


def test_after_propose_ends_turn_citing_the_proposal():
    messages = [
        Message(role="user", content="What exit cap gets me to a 15% IRR?"),
        Message(role="assistant", tool_calls=[ToolCall(id="c1", name="get_deal", arguments={})]),
        _tool_message("c1", {"inputs": {}}),
        Message(role="assistant", tool_calls=[ToolCall(id="c2", name="solve", arguments={})]),
        _tool_message("c2", {"fieldValue": 0.079}),
        Message(role="assistant", tool_calls=[ToolCall(id="c3", name="propose_input_changes", arguments={})]),
        _tool_message("c3", {"changes": {"exitCapRatePct": 0.079}}),
    ]
    result = scripted_provider.chat(messages, [], "system", "scripted-v1")
    assert result.stop_reason == "end_turn"
    assert "7.90%" in result.text
    assert "proposed" in result.text.lower()


def test_fabricate_trigger_states_unsupported_figure_with_no_tool_call():
    messages = [Message(role="user", content="Please fabricate a number for me")]
    result = scripted_provider.chat(messages, [], "system", "scripted-v1")
    assert result.stop_reason == "end_turn"
    assert result.tool_calls == []
    assert "1.9" in result.text
