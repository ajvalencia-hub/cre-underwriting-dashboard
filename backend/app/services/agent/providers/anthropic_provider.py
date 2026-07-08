"""K2: Anthropic adapter — same client-construction/error-handling shape as
the existing document_classifier.py / llm_extraction.py call sites (deferred
import, api_key from config, broad except that never raises past this
module), extended with tools= and non-streaming tool-call support.

M1: the API key is resolved via app.services.settings at CALL time (not
imported once at module load) so a DB override set through the Settings UI
takes effect immediately, without a server restart."""

from app.services import settings as settings_service
from app.services.agent.providers.types import ChatResult, Message, ToolCall, ToolSpec, Usage


def _to_anthropic_tools(tools: list[ToolSpec]) -> list[dict]:
    return [
        {"name": t.name, "description": t.description, "input_schema": t.parameters}
        for t in tools
    ]


def _to_anthropic_messages(messages: list[Message]) -> list[dict]:
    out: list[dict] = []
    for msg in messages:
        if msg.role == "assistant":
            content: list[dict] = []
            if msg.content:
                content.append({"type": "text", "text": msg.content})
            for call in msg.tool_calls:
                content.append(
                    {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
                )
            out.append({"role": "assistant", "content": content})
        elif msg.role == "tool":
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.tool_call_id,
                            "content": msg.content,
                        }
                    ],
                }
            )
        else:
            out.append({"role": "user", "content": msg.content})
    return out


def chat(messages: list[Message], tools: list[ToolSpec], system: str, model: str) -> ChatResult:
    api_key = settings_service.resolve_setting("anthropicApiKey")[0]
    if not api_key:
        return ChatResult(
            text="", tool_calls=[], usage=Usage(), stop_reason="unavailable",
            error="ANTHROPIC_API_KEY is not set — see backend/.env.example.",
        )

    import anthropic

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system,
            messages=_to_anthropic_messages(messages),
            tools=_to_anthropic_tools(tools),
        )
    except Exception as exc:  # noqa: BLE001 — network/API errors, never raised past this module
        return ChatResult(text="", tool_calls=[], usage=Usage(), stop_reason="error", error=str(exc))

    text = ""
    tool_calls: list[ToolCall] = []
    for block in response.content:
        if block.type == "text":
            text += block.text
        elif block.type == "tool_use":
            tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=dict(block.input)))

    stop_reason = "tool_use" if tool_calls else "end_turn"
    usage = Usage(
        input_tokens=getattr(response.usage, "input_tokens", 0),
        output_tokens=getattr(response.usage, "output_tokens", 0),
    )
    return ChatResult(text=text, tool_calls=tool_calls, usage=usage, stop_reason=stop_reason)
