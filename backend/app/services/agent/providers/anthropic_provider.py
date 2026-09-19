"""K2: Anthropic adapter — same client-construction/error-handling shape as
the existing document_classifier.py / llm_extraction.py call sites (deferred
import, api_key from config, broad except that never raises past this
module), extended with tools= and non-streaming tool-call support."""

from typing import TYPE_CHECKING, Any, cast

from app.config import ANTHROPIC_API_KEY
from app.services.agent.providers.types import ChatResult, Message, ToolCall, ToolSpec, Usage

if TYPE_CHECKING:
    from anthropic.types import MessageParam, ToolParam


def _to_anthropic_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {"name": t.name, "description": t.description, "input_schema": t.parameters}
        for t in tools
    ]


def _to_anthropic_messages(messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role == "assistant":
            content: list[dict[str, Any]] = []
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
    if not ANTHROPIC_API_KEY:
        return ChatResult(
            text="", tool_calls=[], usage=Usage(), stop_reason="unavailable",
            error="ANTHROPIC_API_KEY is not set — see backend/.env.example.",
        )

    import anthropic

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system,
            messages=cast("list[MessageParam]", _to_anthropic_messages(messages)),
            tools=cast("list[ToolParam]", _to_anthropic_tools(tools)),
        )
    except Exception as exc:  # noqa: BLE001 — network/API errors, never raised past this module
        return ChatResult(text="", tool_calls=[], usage=Usage(), stop_reason="error", error=str(exc))

    text = ""
    tool_calls: list[ToolCall] = []
    # Duck-typed reads: the SDK's content union carries many block kinds
    # (thinking, server tool use, ...) — only text and tool_use matter here.
    for block in response.content:
        block_type = getattr(block, "type", "")
        if block_type == "text":
            text += str(getattr(block, "text", ""))
        elif block_type == "tool_use":
            raw_input = getattr(block, "input", None)
            arguments = dict(raw_input) if isinstance(raw_input, dict) else {}
            tool_calls.append(
                ToolCall(id=str(getattr(block, "id", "")), name=str(getattr(block, "name", "")), arguments=arguments)
            )

    stop_reason = "tool_use" if tool_calls else "end_turn"
    usage = Usage(
        input_tokens=getattr(response.usage, "input_tokens", 0),
        output_tokens=getattr(response.usage, "output_tokens", 0),
    )
    return ChatResult(text=text, tool_calls=tool_calls, usage=usage, stop_reason=stop_reason)
