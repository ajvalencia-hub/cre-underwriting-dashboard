"""K2: vendor-neutral shapes both provider adapters speak. The orchestration
loop (K4) is written entirely against these — it never sees an Anthropic or
OpenAI wire format directly."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolSpec:
    """One tool's schema, vendor-neutral. Each adapter translates this into
    its own wire shape (Anthropic's input_schema vs. OpenAI's function.parameters)."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema for the tool's arguments


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    """One turn in the conversation. `tool_calls` is set on assistant messages
    that requested tools; `tool_call_id`/`name` are set on tool-result messages
    that answer a specific prior call."""

    role: str  # "user" | "assistant" | "tool"
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class ChatResult:
    """One provider call's outcome. `stop_reason` is one of:
    "tool_use" (the model wants to call tools — see tool_calls),
    "end_turn" (plain text, turn is done),
    "unavailable" (no API key configured for this provider),
    "error" (the call failed — see `error`).
    text/tool_calls are always populated as best-effort even on "error" (empty)."""

    text: str
    tool_calls: list[ToolCall]
    usage: Usage
    stop_reason: str
    error: str | None = None


class ProviderError(Exception):
    """Raised only for programmer errors (e.g. unknown provider name in the
    factory) — normal runtime failures (missing key, API error) are reported
    via ChatResult.stop_reason, never an exception, so the agent runner never
    needs a try/except around a provider call."""
