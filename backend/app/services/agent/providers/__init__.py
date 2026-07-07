"""K2: provider factory — selects the Anthropic or OpenAI adapter by
AGENT_PROVIDER and picks its configured model. Both adapters expose the same
chat(messages, tools, system, model) -> ChatResult signature (see types.py),
so the runner (K4) never branches on provider."""

from app.config import ANTHROPIC_AGENT_MODEL, OPENAI_AGENT_MODEL
from app.services.agent.providers import anthropic_provider, openai_provider
from app.services.agent.providers.types import ChatResult, Message, ToolSpec, Usage

_PROVIDERS = {
    "anthropic": (anthropic_provider, ANTHROPIC_AGENT_MODEL),
    "openai": (openai_provider, OPENAI_AGENT_MODEL),
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
    module, model = entry
    return module.chat(messages, tools, system, model)
