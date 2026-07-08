"""M3: per-task model routing — local-first, cloud-fallback. Every LLM call
in this app, regardless of task (classification / extraction / agent),
routes through run_task() so there's exactly one place that resolves
routing settings, attempts a fallback on failure, and records a usage
event — not three independent copies of that logic.

[FIN] fallback model choice (see DECISIONS.md): a fallback attempt uses the
fallback provider's OWN default model setting (via providers.chat_with's
existing per-provider resolution), never a per-task "fallback model"
setting. There's no N-provider x M-task model-settings matrix to keep in
sync — fallback is rare, and correctness (falling back at all) matters more
than model-tier tuning on the rare path that fires.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import LlmUsageEvent
from app.services import settings as settings_service
from app.services.agent.providers import chat_with
from app.services.agent.providers.types import ChatResult, Message, ToolSpec, Usage

TASKS = ("classification", "extraction", "agent")
_TERMINAL_FAILURE_REASONS = ("unavailable", "error")


@dataclass(frozen=True)
class RoutingDecision:
    provider: str
    model: str
    fallback: str  # "none" (or any falsy/unknown value) disables fallback


def resolve_task(task: str) -> RoutingDecision:
    if task not in TASKS:
        raise ValueError(f"Unknown routing task '{task}'. Valid options: {', '.join(TASKS)}.")
    provider = settings_service.resolve_setting(f"routing.{task}.provider")[0]
    model = settings_service.resolve_setting(f"routing.{task}.model")[0]
    fallback = settings_service.resolve_setting(f"routing.{task}.fallback")[0]
    return RoutingDecision(provider=provider, model=model, fallback=fallback)


def chat_with_fallback(
    provider: str, model: str, fallback: str,
    messages: list[Message], tools: list[ToolSpec], system: str,
) -> tuple[ChatResult, str, str]:
    """Tries `provider`/`model` first; if that comes back unavailable/error
    and a distinct fallback provider is configured, tries it once (its own
    default model). Returns (result, providerUsed, modelUsed) so the caller
    can log which one actually answered."""
    result = chat_with(provider, messages, tools, system, model=model or None)
    if result.stop_reason in _TERMINAL_FAILURE_REASONS and fallback and fallback not in ("none", provider):
        fallback_result = chat_with(fallback, messages, tools, system)
        return fallback_result, fallback, ""
    return result, provider, model


def record_usage(
    task: str, provider: str, model: str, usage: Usage, deal_id: str | None = None,
    db: Session | None = None,
) -> None:
    """Logs every attempt, including a both-unavailable one (0 tokens) —
    the usage trail is observability data, not just a cost ledger, so a
    "nothing answered" row is itself useful information.

    `db`: when the caller already has a request-scoped session (the K4
    runner, mid-turn), pass it — the row rides along on that transaction's
    own commit, no separate DB round-trip. Callers with no session in scope
    (document_classifier.py, llm_extraction.py) leave it unset and get a
    short-lived one of their own, committed immediately."""
    if db is not None:
        db.add(LlmUsageEvent(
            task=task, provider=provider, model=model,
            input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
            deal_id=deal_id,
        ))
        return
    with SessionLocal() as own_db:
        own_db.add(LlmUsageEvent(
            task=task, provider=provider, model=model,
            input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
            deal_id=deal_id,
        ))
        own_db.commit()


def run_task(
    task: str, messages: list[Message], tools: list[ToolSpec], system: str,
    deal_id: str | None = None,
) -> tuple[ChatResult, str, str]:
    """The chokepoint: resolve this task's routing, attempt with fallback,
    record usage. Classification and extraction call this directly (no
    per-call override concept exists for them). The agent runner does NOT
    call this directly for the primary attempt — a thread's own explicit
    provider choice (K1-era per-conversation UX) takes priority over
    routing.agent.provider there; see runner.py, which calls
    chat_with_fallback()/record_usage() with the thread's provider as
    primary and routing.agent.fallback as the fallback instead."""
    decision = resolve_task(task)
    result, provider_used, model_used = chat_with_fallback(
        decision.provider, decision.model, decision.fallback, messages, tools, system,
    )
    record_usage(task, provider_used, model_used, result.usage, deal_id)
    return result, provider_used, model_used
