"""M2: Ollama (local) adapter — same chat(messages, tools, system, model) ->
ChatResult contract as anthropic_provider.py/openai_provider.py, using
httpx (already a dependency) to POST Ollama's native /api/chat endpoint.

Confirmed against Ollama's own docs (not assumed) before writing this:
- Request: {model, messages, tools, stream: false}, tools OpenAI-function-
  shaped ({type:"function", function:{name, description, parameters}}).
- Response: {message: {role, content, tool_calls?: [{function: {name,
  arguments}}]}, done, done_reason, prompt_eval_count, eval_count, ...}.
- tool_calls[].function.arguments is ALREADY a parsed JSON object on the
  native API (unlike OpenAI's Chat Completions API, which returns a JSON
  *string*) — so unlike openai_provider.py, no json.loads/json.dumps is
  needed here at all.
- Ollama's native tool_calls carry NO id field (correlated by function name
  and message order, not an id, unlike Anthropic/OpenAI) — this adapter
  synthesizes a per-response positional id ("call_0", "call_1", ...) so it
  can still satisfy the vendor-neutral ToolCall.id field the rest of this
  codebase (the K4 runner's tool_call_id round-trip within a turn) relies
  on; that id is dropped again when translating tool_calls back into
  Ollama's own message format (Ollama never receives or expects it).

"unavailable" vs "error": Ollama has no API key to check up front (the
spec's own point — "Local (Ollama) needs no key"), so the reachability
check IS the unavailable check, done reactively rather than proactively.
A connection failure (host unreachable/timeout — Ollama isn't running)
degrades to "unavailable", the same terminal state a missing key produces
for the other two adapters. A response FROM a reachable Ollama server that
still fails (bad status, malformed body) is "error" — the call was
attempted, something specific went wrong, mirroring the other adapters'
broad-except-never-raise convention."""

from app.services import settings as settings_service
from app.services.agent.providers.types import ChatResult, Message, ToolCall, ToolSpec, Usage


def _to_ollama_tools(tools: list[ToolSpec]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
        }
        for t in tools
    ]


def _to_ollama_messages(messages: list[Message], system: str) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system}]
    for msg in messages:
        if msg.role == "assistant":
            entry: dict = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                entry["tool_calls"] = [
                    {"function": {"name": call.name, "arguments": call.arguments}}
                    for call in msg.tool_calls
                ]
            out.append(entry)
        elif msg.role == "tool":
            out.append({"role": "tool", "content": msg.content})
        else:
            out.append({"role": "user", "content": msg.content})
    return out


def chat(messages: list[Message], tools: list[ToolSpec], system: str, model: str) -> ChatResult:
    base_url = settings_service.resolve_setting("ollamaBaseUrl")[0]

    import httpx

    try:
        response = httpx.post(
            f"{base_url}/api/chat",
            json={
                "model": model,
                "messages": _to_ollama_messages(messages, system),
                "tools": _to_ollama_tools(tools),
                "stream": False,
            },
            timeout=120.0,
        )
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        return ChatResult(
            text="", tool_calls=[], usage=Usage(), stop_reason="unavailable",
            error=f"Ollama unreachable at {base_url}: {exc}",
        )
    except Exception as exc:  # noqa: BLE001 — never raised past this module
        return ChatResult(text="", tool_calls=[], usage=Usage(), stop_reason="error", error=str(exc))

    try:
        response.raise_for_status()
        data = response.json()
    except Exception as exc:  # noqa: BLE001 — bad status / malformed body
        return ChatResult(text="", tool_calls=[], usage=Usage(), stop_reason="error", error=str(exc))

    message = data.get("message") or {}
    text = message.get("content") or ""
    tool_calls: list[ToolCall] = []
    for i, call in enumerate(message.get("tool_calls") or []):
        function = call.get("function") or {}
        tool_calls.append(
            ToolCall(id=f"call_{i}", name=function.get("name", ""), arguments=function.get("arguments") or {})
        )

    stop_reason = "tool_use" if tool_calls else "end_turn"
    usage = Usage(
        input_tokens=data.get("prompt_eval_count") or 0,
        output_tokens=data.get("eval_count") or 0,
    )
    return ChatResult(text=text, tool_calls=tool_calls, usage=usage, stop_reason=stop_reason)
