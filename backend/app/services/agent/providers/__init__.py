"""K2: provider factory — selects the Anthropic or OpenAI adapter by
AGENT_PROVIDER and picks its configured model. Both adapters expose the same
chat(messages, tools, system, model) -> ChatResult signature (see types.py),
so the runner (K4) never branches on provider.

M1: each provider's default MODEL is resolved via app.services.settings at
CALL time (not baked into a dict at import), same reasoning as the API-key
resolution inside each adapter — a DB override takes effect immediately."""

from app.services import settings as settings_service
from app.services.agent.providers import anthropic_provider, ollama_provider, openai_provider, scripted_provider
from app.services.agent.providers.types import ChatResult, Message, ToolSpec, Usage

_PROVIDER_MODULES = {
    "anthropic": anthropic_provider,
    "openai": openai_provider,
    "ollama": ollama_provider,
    # K11: deterministic, network-free — only ever selected by explicitly
    # setting AGENT_PROVIDER=scripted (the Playwright e2e config does this).
    "scripted": scripted_provider,
}

# Which settings-catalog key supplies each provider's default model; None
# means the module ignores the model argument (the scripted stub).
_DEFAULT_MODEL_SETTING = {
    "anthropic": "anthropicAgentModel",
    "openai": "openaiAgentModel",
    "ollama": "ollamaAgentModel",
    "scripted": None,
}


def chat_with(
    provider_name: str, messages: list[Message], tools: list[ToolSpec], system: str,
    model: str | None = None,
) -> ChatResult:
    """Dispatch to the named provider. Unknown provider names return an
    "unavailable" result rather than raising — a bad provider value should
    degrade the same way a missing key does, not 500.

    M3: `model` is an optional override — when omitted (every pre-M3
    caller, e.g. the K4 runner's default path), the provider's own default
    model setting is resolved as before; when given (model_router.py's
    per-task routing), it's used directly. This keeps every existing call
    site's behavior byte-identical while letting per-task routing pick a
    specific model without needing its own copy of the factory dispatch."""
    module = _PROVIDER_MODULES.get(provider_name)
    if module is None:
        return ChatResult(
            text="", tool_calls=[], usage=Usage(), stop_reason="unavailable",
            error=(
                f"Unknown agent provider '{provider_name}'. "
                f"Valid options: {', '.join(_PROVIDER_MODULES)}."
            ),
        )
    if model:
        resolved_model = model
    else:
        setting_key = _DEFAULT_MODEL_SETTING[provider_name]
        resolved_model = settings_service.resolve_setting(setting_key)[0] if setting_key else "scripted-v1"
    return module.chat(messages, tools, system, resolved_model)
