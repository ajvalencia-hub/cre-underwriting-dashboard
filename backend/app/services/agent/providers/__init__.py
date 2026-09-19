"""K2: provider factory — selects the Anthropic, OpenAI or scripted adapter
by name and picks its configured model. Every adapter exposes the same
chat(messages, tools, system, model) -> ChatResult signature (see types.py),
so the runner (K4) never branches on provider."""

from collections.abc import Callable

from app.config import ANTHROPIC_AGENT_MODEL, OPENAI_AGENT_MODEL
from app.services.agent.providers import anthropic_provider, openai_provider, scripted_provider
from app.services.agent.providers.types import ChatResult, Message, ToolSpec, Usage

ChatFn = Callable[[list[Message], list[ToolSpec], str, str], ChatResult]

_PROVIDERS: dict[str, tuple[ChatFn, str]] = {
    "anthropic": (anthropic_provider.chat, ANTHROPIC_AGENT_MODEL),
    "openai": (openai_provider.chat, OPENAI_AGENT_MODEL),
    # K11: deterministic, network-free — only ever selected by explicitly
    # setting AGENT_PROVIDER=scripted (the Playwright e2e config does this).
    "scripted": (scripted_provider.chat, "scripted-v1"),
}


def chat_with(
    provider_name: str, messages: list[Message], tools: list[ToolSpec], system: str
) -> ChatResult:
    """Dispatch to the named provider's default model. Unknown provider names
    return an "unavailable" result rather than raising — a bad AGENT_PROVIDER
    value should degrade the same way a missing key does, not 500."""
    entry = _PROVIDERS.get(provider_name)
    if entry is None:
        return ChatResult(
            text="", tool_calls=[], usage=Usage(), stop_reason="unavailable",
            error=f"Unknown agent provider '{provider_name}'. Valid options: {', '.join(_PROVIDERS)}.",
        )
    chat, model = entry
    return chat(messages, tools, system, model)
