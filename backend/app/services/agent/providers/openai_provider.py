"""K2: OpenAI adapter (Chat Completions, non-streaming, function-calling).
Mirrors anthropic_provider.py's shape exactly — same key-missing/error
handling contract — so the runner (K4) treats both providers identically.

M1: the API key is resolved via app.services.settings at CALL time, same
as anthropic_provider.py — see that module's docstring."""

import json

from app.services import settings as settings_service
from app.services.agent.providers.types import ChatResult, Message, ToolCall, ToolSpec, Usage


def _to_openai_tools(tools: list[ToolSpec]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
        }
        for t in tools
    ]


def _to_openai_messages(messages: list[Message], system: str) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system}]
    for msg in messages:
        if msg.role == "assistant":
            entry: dict = {"role": "assistant", "content": msg.content or None}
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
    api_key = settings_service.resolve_setting("openaiApiKey")[0]
    if not api_key:
        return ChatResult(
            text="", tool_calls=[], usage=Usage(), stop_reason="unavailable",
            error="OPENAI_API_KEY is not set — see backend/.env.example.",
        )

    import openai

    try:
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=_to_openai_messages(messages, system),
            tools=_to_openai_tools(tools),
        )
    except Exception as exc:  # noqa: BLE001 — network/API errors, never raised past this module
        return ChatResult(text="", tool_calls=[], usage=Usage(), stop_reason="error", error=str(exc))

    message = response.choices[0].message
    text = message.content or ""
    tool_calls: list[ToolCall] = []
    for call in message.tool_calls or []:
        try:
            arguments = json.loads(call.function.arguments) if call.function.arguments else {}
        except json.JSONDecodeError:
            arguments = {}
        tool_calls.append(ToolCall(id=call.id, name=call.function.name, arguments=arguments))

    stop_reason = "tool_use" if tool_calls else "end_turn"
    usage = Usage(
        input_tokens=getattr(response.usage, "prompt_tokens", 0) if response.usage else 0,
        output_tokens=getattr(response.usage, "completion_tokens", 0) if response.usage else 0,
    )
    return ChatResult(text=text, tool_calls=tool_calls, usage=usage, stop_reason=stop_reason)
