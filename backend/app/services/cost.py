"""M5: approximate $ cost estimation for LLM usage. A static price table,
not a live-pricing API — provider pricing pages are the real source of
truth; this exists so the Settings > Usage view can show a rough dollar
figure alongside raw token counts, not to reconcile a real invoice.
Update the table as pricing changes.
"""

from app.services.agent.providers.types import Usage

# $ per 1,000,000 tokens, (input, output). Approximate.
_PRICE_PER_1M_TOKENS: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (15.0, 75.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (0.80, 4.0),
    "gpt-5.1": (2.50, 10.0),
}


def estimate_cost(provider: str, model: str, usage: Usage) -> float | None:
    """None means "unknown cost" (an unrecognized model) — deliberately
    distinct from a known $0 (Ollama, local — always $0, tokens are still
    logged for observability but there's no bill for them)."""
    if provider == "ollama":
        return 0.0
    prices = _PRICE_PER_1M_TOKENS.get(model)
    if prices is None:
        return None
    input_price, output_price = prices
    return (
        (usage.input_tokens / 1_000_000) * input_price
        + (usage.output_tokens / 1_000_000) * output_price
    )
