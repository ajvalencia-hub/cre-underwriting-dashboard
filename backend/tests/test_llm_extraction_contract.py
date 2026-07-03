"""Regression tests for FINDINGS.md M2 (LLM contract must pin percent scale)
and M3 (input truncation must produce a warning, not silence).
"""

import json

import anthropic
import pytest

from app.services.extraction import llm_extraction

_MINIMAL_REPLY = json.dumps({"documentType": "other"})


class _StubClient:
    """Stands in for anthropic.Anthropic: records the prompt, returns a fixed reply."""

    last_prompt: str | None = None

    def __init__(self, api_key):
        self.messages = self

    def create(self, **kwargs):
        _StubClient.last_prompt = kwargs["messages"][0]["content"]
        block = type("Block", (), {"text": _MINIMAL_REPLY})()
        return type("Resp", (), {"content": [block]})()


@pytest.fixture
def stubbed_llm(monkeypatch):
    _StubClient.last_prompt = None
    monkeypatch.setattr(anthropic, "Anthropic", _StubClient)
    monkeypatch.setattr(llm_extraction, "ANTHROPIC_API_KEY", "test-key")


def test_contract_pins_percent_scale_as_decimal_fraction():
    # M2: a model returning 5 vs 0.05 is undetectable at validation time, so
    # the scale must be part of the prompt contract itself.
    assert "decimal fraction" in llm_extraction._CONTRACT_DESCRIPTION
    assert "0.05" in llm_extraction._CONTRACT_DESCRIPTION


def test_truncated_input_emits_warning(stubbed_llm):
    text = "x" * (llm_extraction._MAX_TEXT_CHARS + 5000)
    out = llm_extraction.extract_with_llm("offering_memorandum", text, "om.pdf", [])
    assert out["result"] is not None
    assert any("not extracted" in w for w in out["result"]["warnings"])
    # And the prompt really was cut at the limit:
    assert len(_StubClient.last_prompt) < len(text)


def test_short_input_emits_no_truncation_warning(stubbed_llm):
    out = llm_extraction.extract_with_llm("offering_memorandum", "short document", "om.pdf", [])
    assert out["result"] is not None
    assert out["result"]["warnings"] == []
