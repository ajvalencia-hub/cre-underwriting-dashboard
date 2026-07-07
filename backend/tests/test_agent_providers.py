"""K2: dual-provider agent adapters — mocked at the SDK-client level (no live
network calls, matching this repo's existing LLM-test discipline, e.g.
test_llm_extraction_contract.py's _StubClient pattern). Covers: each
adapter's happy path, tool-call path, missing-key degradation, call-failure
handling, and the factory's dispatch/normalization."""

import anthropic
import openai
import pytest

from app.services.agent.providers import anthropic_provider, openai_provider
from app.services.agent.providers import chat_with
from app.services.agent.providers.types import Message, ToolCall, ToolSpec

_TOOLS = [ToolSpec(name="get_deal", description="Fetch a deal.", parameters={"type": "object", "properties": {}})]


# ---------------------------------------------------------------------------
# Anthropic stubs
# ---------------------------------------------------------------------------

class _AnthropicBlock:
    def __init__(self, type_, **kw):
        self.type = type_
        for k, v in kw.items():
            setattr(self, k, v)


class _AnthropicUsage:
    def __init__(self, input_tokens=10, output_tokens=5):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _AnthropicResponse:
    def __init__(self, content, usage=None):
        self.content = content
        self.usage = usage or _AnthropicUsage()


class _StubAnthropicClient:
    response = None
    raises = False
    captured_kwargs = None

    def __init__(self, api_key):
        self.messages = self

    def create(self, **kwargs):
        _StubAnthropicClient.captured_kwargs = kwargs
        if _StubAnthropicClient.raises:
            raise RuntimeError("anthropic call failed")
        return _StubAnthropicClient.response


@pytest.fixture
def stub_anthropic(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", _StubAnthropicClient)
    monkeypatch.setattr(anthropic_provider, "ANTHROPIC_API_KEY", "test-key")
    _StubAnthropicClient.raises = False
    _StubAnthropicClient.captured_kwargs = None
    yield _StubAnthropicClient


def test_anthropic_missing_key_is_unavailable(monkeypatch):
    monkeypatch.setattr(anthropic_provider, "ANTHROPIC_API_KEY", "")
    result = anthropic_provider.chat([Message(role="user", content="hi")], [], "system", "model")
    assert result.stop_reason == "unavailable"
    assert result.error


def test_anthropic_text_only_response(stub_anthropic):
    stub_anthropic.response = _AnthropicResponse([_AnthropicBlock("text", text="the DSCR is 1.4x")])
    result = anthropic_provider.chat([Message(role="user", content="what's the dscr")], _TOOLS, "system", "model")
    assert result.stop_reason == "end_turn"
    assert result.text == "the DSCR is 1.4x"
    assert result.tool_calls == []
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 5
    assert stub_anthropic.captured_kwargs["tools"][0]["name"] == "get_deal"


def test_anthropic_tool_use_response(stub_anthropic):
    stub_anthropic.response = _AnthropicResponse(
        [_AnthropicBlock("tool_use", id="call_1", name="get_deal", input={"dealId": "abc"})]
    )
    result = anthropic_provider.chat([Message(role="user", content="screen this deal")], _TOOLS, "system", "model")
    assert result.stop_reason == "tool_use"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call_1"
    assert result.tool_calls[0].name == "get_deal"
    assert result.tool_calls[0].arguments == {"dealId": "abc"}


def test_anthropic_call_failure_is_error_not_exception(stub_anthropic):
    stub_anthropic.raises = True
    result = anthropic_provider.chat([Message(role="user", content="hi")], [], "system", "model")
    assert result.stop_reason == "error"
    assert result.error


def test_anthropic_tool_result_message_round_trips(stub_anthropic):
    stub_anthropic.response = _AnthropicResponse([_AnthropicBlock("text", text="done")])
    messages = [
        Message(role="user", content="screen this deal"),
        Message(
            role="assistant",
            tool_calls=[ToolCall(id="call_1", name="get_deal", arguments={"dealId": "abc"})],
        ),
        Message(role="tool", tool_call_id="call_1", content='{"name": "Test Deal"}'),
    ]
    anthropic_provider.chat(messages, _TOOLS, "system", "model")
    sent = stub_anthropic.captured_kwargs["messages"]
    assert sent[1]["content"][0]["type"] == "tool_use"
    assert sent[2]["content"][0]["type"] == "tool_result"
    assert sent[2]["content"][0]["tool_use_id"] == "call_1"


# ---------------------------------------------------------------------------
# OpenAI stubs
# ---------------------------------------------------------------------------

class _OpenAIFunctionCall:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _OpenAIToolCall:
    def __init__(self, id_, name, arguments):
        self.id = id_
        self.function = _OpenAIFunctionCall(name, arguments)


class _OpenAIMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _OpenAIChoice:
    def __init__(self, message):
        self.message = message


class _OpenAIUsage:
    def __init__(self, prompt_tokens=8, completion_tokens=4):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _OpenAIResponse:
    def __init__(self, message, usage=None):
        self.choices = [_OpenAIChoice(message)]
        self.usage = usage or _OpenAIUsage()


class _StubOpenAIClient:
    response = None
    raises = False
    captured_kwargs = None

    def __init__(self, api_key):
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        _StubOpenAIClient.captured_kwargs = kwargs
        if _StubOpenAIClient.raises:
            raise RuntimeError("openai call failed")
        return _StubOpenAIClient.response


@pytest.fixture
def stub_openai(monkeypatch):
    monkeypatch.setattr(openai, "OpenAI", _StubOpenAIClient)
    monkeypatch.setattr(openai_provider, "OPENAI_API_KEY", "test-key")
    _StubOpenAIClient.raises = False
    _StubOpenAIClient.captured_kwargs = None
    yield _StubOpenAIClient


def test_openai_missing_key_is_unavailable(monkeypatch):
    monkeypatch.setattr(openai_provider, "OPENAI_API_KEY", "")
    result = openai_provider.chat([Message(role="user", content="hi")], [], "system", "model")
    assert result.stop_reason == "unavailable"
    assert result.error


def test_openai_text_only_response(stub_openai):
    stub_openai.response = _OpenAIResponse(_OpenAIMessage(content="the DSCR is 1.4x"))
    result = openai_provider.chat([Message(role="user", content="what's the dscr")], _TOOLS, "system", "model")
    assert result.stop_reason == "end_turn"
    assert result.text == "the DSCR is 1.4x"
    assert result.tool_calls == []
    assert result.usage.input_tokens == 8
    assert result.usage.output_tokens == 4
    assert stub_openai.captured_kwargs["tools"][0]["function"]["name"] == "get_deal"


def test_openai_tool_use_response(stub_openai):
    import json

    stub_openai.response = _OpenAIResponse(
        _OpenAIMessage(
            content=None,
            tool_calls=[_OpenAIToolCall("call_1", "get_deal", json.dumps({"dealId": "abc"}))],
        )
    )
    result = openai_provider.chat([Message(role="user", content="screen this deal")], _TOOLS, "system", "model")
    assert result.stop_reason == "tool_use"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call_1"
    assert result.tool_calls[0].name == "get_deal"
    assert result.tool_calls[0].arguments == {"dealId": "abc"}


def test_openai_call_failure_is_error_not_exception(stub_openai):
    stub_openai.raises = True
    result = openai_provider.chat([Message(role="user", content="hi")], [], "system", "model")
    assert result.stop_reason == "error"
    assert result.error


def test_openai_malformed_tool_arguments_degrade_to_empty_dict(stub_openai):
    stub_openai.response = _OpenAIResponse(
        _OpenAIMessage(content=None, tool_calls=[_OpenAIToolCall("call_1", "get_deal", "not-json")])
    )
    result = openai_provider.chat([Message(role="user", content="hi")], _TOOLS, "system", "model")
    assert result.tool_calls[0].arguments == {}


# ---------------------------------------------------------------------------
# Factory dispatch + cross-vendor normalization
# ---------------------------------------------------------------------------

def test_factory_dispatches_to_anthropic(stub_anthropic):
    stub_anthropic.response = _AnthropicResponse([_AnthropicBlock("text", text="hi from anthropic")])
    result = chat_with("anthropic", [Message(role="user", content="hi")], [], "system")
    assert result.text == "hi from anthropic"


def test_factory_dispatches_to_openai(stub_openai):
    stub_openai.response = _OpenAIResponse(_OpenAIMessage(content="hi from openai"))
    result = chat_with("openai", [Message(role="user", content="hi")], [], "system")
    assert result.text == "hi from openai"


def test_factory_unknown_provider_is_unavailable_not_exception():
    result = chat_with("not-a-real-provider", [Message(role="user", content="hi")], [], "system")
    assert result.stop_reason == "unavailable"
    assert result.error


def test_both_vendors_normalize_tool_calls_identically(stub_anthropic, stub_openai):
    import json

    stub_anthropic.response = _AnthropicResponse(
        [_AnthropicBlock("tool_use", id="call_1", name="get_deal", input={"dealId": "abc"})]
    )
    stub_openai.response = _OpenAIResponse(
        _OpenAIMessage(
            content=None,
            tool_calls=[_OpenAIToolCall("call_1", "get_deal", json.dumps({"dealId": "abc"}))],
        )
    )
    a = chat_with("anthropic", [Message(role="user", content="screen it")], _TOOLS, "system")
    o = chat_with("openai", [Message(role="user", content="screen it")], _TOOLS, "system")
    assert a.stop_reason == o.stop_reason == "tool_use"
    assert a.tool_calls[0].name == o.tool_calls[0].name
    assert a.tool_calls[0].arguments == o.tool_calls[0].arguments
