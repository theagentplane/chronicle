"""Conformance tests: every adapter normalizes to the same LLMOutput shapes.

Fixtures live in tests/fixtures/providers/<provider>/{request,response_text,response_tools}.json.
Both a plain-text response and a tool-call response must normalize correctly.
Unknown/malformed payloads fall back to generic; recording never raises; no
provider SDK is imported (fake clients only).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import chronicle
from chronicle import boundary, reset_session
from chronicle.providers import get_provider, register_provider

ROOT = Path(__file__).resolve().parent / "fixtures" / "providers"

_FIXTURE_DIR = {
    "openai": "openai_chat",
    "anthropic": "anthropic",
    "openai_responses": "openai_responses",
}


def _load(provider: str, name: str):
    return json.loads((ROOT / _FIXTURE_DIR.get(provider, provider) / name).read_text())


@pytest.mark.layer1
@pytest.mark.parametrize("provider", ["openai", "anthropic", "openai_responses", "generic"])
def test_text_response_normalizes(provider):
    adapter = get_provider(provider)
    fixture_provider = "openai" if provider == "generic" else provider
    payload = _load(fixture_provider, "response_text.json")
    llm, model = adapter.parse_response(payload)
    assert llm.text == "Order A-4471 totals $47.00."
    assert llm.tool_calls == []
    assert (
        llm.finish_reason in ("stop", "end_turn", "completed", None) or llm.finish_reason == "stop"
    )
    assert (llm.usage.input_tokens, llm.usage.output_tokens) == (21, 9)
    assert model in ("gpt-4o", "claude-sonnet-4-6")


@pytest.mark.layer1
@pytest.mark.parametrize("provider", ["openai", "anthropic", "openai_responses"])
def test_tool_response_normalizes(provider):
    adapter = get_provider(provider)
    llm, _ = adapter.parse_response(_load(provider, "response_tools.json"))
    assert len(llm.tool_calls) == 1
    call = llm.tool_calls[0]
    assert call.name == "refund"
    assert call.arguments == {"order_id": "A-4471", "amount_cents": 4700}
    assert llm.finish_reason == "tool_calls"
    assert (llm.usage.input_tokens, llm.usage.output_tokens) == (21, 14)


@pytest.mark.layer1
@pytest.mark.parametrize("provider", ["openai", "anthropic", "openai_responses"])
def test_request_captures_system_prompt_as_typed_messages(provider):
    adapter = get_provider(provider)
    request, messages = adapter.parse_request(_load(provider, "request.json"))
    assert request.model in ("gpt-4o", "claude-sonnet-4-6")
    assert request.provider == provider
    roles = [m.role for m in messages]
    assert "system" in roles  # system/instructions lifted, not dropped
    assert any("refund order" in str(m.content) for m in messages)


@pytest.mark.layer1
def test_unknown_provider_and_malformed_response_fall_back_to_generic():
    adapter = get_provider("gemini-not-yet-supported")
    assert adapter.name == "generic"
    llm, model = adapter.parse_response({"weird": "shape"})
    assert llm.text is None and llm.tool_calls == [] and model is None
    llm2, _ = adapter.parse_response(None)
    assert llm2.text is None
    # Recording never raises, even on garbage.
    session = reset_session()
    session.begin_trace("t-fallback")

    @boundary("llm", kind="llm", provider="nope")
    def call() -> dict:
        return {"completion": "ok"}

    assert call() == {"completion": "ok"}


@pytest.mark.layer1
def test_wrap_auto_detects_responses_and_anthropic_clients():
    class _Responses:
        def create(self, **kwargs):
            return _load("openai_responses", "response_text.json")

    class ResponsesClient:
        responses = _Responses()

    client = chronicle.wrap(ResponsesClient())
    session = reset_session()
    session.begin_trace("t-resp")
    client.responses.create(model="gpt-4o", input="hi", instructions="sys")
    env = session._recorded_envelopes[-1]
    assert env.output.llm.text == "Order A-4471 totals $47.00."
    assert env.attributes["gen_ai.provider.name"] == "openai_responses"
    assert [m.role for m in env.input.messages] == ["system", "user"]

    class _Messages:
        def create(self, **kwargs):
            return _load("anthropic", "response_text.json")

    class AnthropicClient:
        messages = _Messages()

    client2 = chronicle.wrap(AnthropicClient())
    session2 = reset_session()
    session2.begin_trace("t-anth")
    client2.messages.create(
        model="claude-sonnet-4-6", system="sys", messages=[{"role": "user", "content": "hi"}]
    )
    env2 = session2._recorded_envelopes[-1]
    assert env2.output.llm.text == "Order A-4471 totals $47.00."
    assert env2.attributes["gen_ai.provider.name"] == "anthropic"
    assert env2.input.messages[0].role == "system"


@pytest.mark.layer1
def test_boundary_provider_records_raw_value_and_tool_calls():
    session = reset_session()
    session.begin_trace("t-bound")

    @boundary("agent", kind="llm", provider="openai")
    def agent(model: str, messages: list) -> dict:
        return _load("openai_chat", "response_tools.json")

    agent("gpt-4o", [{"role": "user", "content": "hi"}])
    env = session._recorded_envelopes[-1]
    assert env.output.llm.tool_calls[0].name == "refund"
    assert env.output.llm.tool_calls[0].arguments["amount_cents"] == 4700
    assert env.output.value["choices"][0]["finish_reason"] == "tool_calls"  # raw kept
    assert env.attributes["gen_ai.provider.name"] == "openai"


@pytest.mark.layer1
def test_registry_allows_custom_provider():
    class Mine:
        name = "mine"

        def parse_request(self, kwargs):
            from chronicle.envelope.genai import LLMRequest

            return LLMRequest(model="m", provider="mine"), []

        def parse_response(self, response):
            from chronicle.envelope.schema import LLMOutput

            return LLMOutput(text="hi"), "m"

    register_provider(Mine())
    assert get_provider("mine").name == "mine"
