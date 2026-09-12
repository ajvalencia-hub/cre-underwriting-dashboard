"""K2: OpenAI adapter (Chat Completions, non-streaming, function-calling).
Mirrors anthropic_provider.py's shape exactly — same key-missing/error
handling contract — so the runner (K4) treats both providers identically."""

import json
from typing import TYPE_CHECKING, Any, cast

from app.config import OPENAI_API_KEY
from app.services.agent.providers.types import ChatResult, Message, ToolCall, ToolSpec, Usage

if TYPE_CHECKING:
    from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam


def _to_openai_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
        }
        for t in tools
    ]


def _to_openai_messages(messages: list[Message], system: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for msg in messages:
        if msg.role == "assistant":
            entry: dict[str, Any] = {"role": "assistant", "content": msg.content or None}
            if msg.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                    }
                    for call in msg.tool_calls
                ]
            out.append(entry)
        elif msg.role == "tool":
            out.append({"role": "tool", "tool_call_id": msg.tool_call_id, "content": msg.content})
        else:
            out.append({"role": "user", "content": msg.content})
    return out


def chat(messages: list[Message], tools: list[ToolSpec], system: str, model: str) -> ChatResult:
    if not OPENAI_API_KEY:
        return ChatResult(
            text="", tool_calls=[], usage=Usage(), stop_reason="unavailable",
            error="OPENAI_API_KEY is not set — see backend/.env.example.",
        )

    import openai

    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=model,
            messages=cast("list[ChatCompletionMessageParam]", _to_openai_messages(messages, system)),
            tools=cast("list[ChatCompletionToolParam]", _to_openai_tools(tools)),
        )
    except Exception as exc:  # noqa: BLE001 — network/API errors, never raised past this module
        return ChatResult(text="", tool_calls=[], usage=Usage(), stop_reason="error", error=str(exc))

    message = response.choices[0].message
    text = message.content or ""
    tool_calls: list[ToolCall] = []
    for call in message.tool_calls or []:
        # openai>=2 types tool_calls as a function|custom union; only
        # function calls carry a name + JSON arguments we can dispatch.
        function = getattr(call, "function", None)
        if function is None:
            continue
        raw_arguments = getattr(function, "arguments", "") or ""
        try:
            arguments = json.loads(raw_arguments) if raw_arguments else {}
        except json.JSONDecodeError:
            arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        tool_calls.append(ToolCall(id=str(call.id), name=str(getattr(function, "name", "")), arguments=arguments))

    stop_reason = "tool_use" if tool_calls else "end_turn"
    usage = Usage(
        input_tokens=getattr(response.usage, "prompt_tokens", 0) if response.usage else 0,
        output_tokens=getattr(response.usage, "completion_tokens", 0) if response.usage else 0,
    )
    return ChatResult(text=text, tool_calls=tool_calls, usage=usage, stop_reason=stop_reason)
