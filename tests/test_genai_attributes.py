"""Model, sampling and tool definitions are stored as OTel GenAI span attributes, and
usage is normalized into one shape regardless of provider."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

import chronicle
from chronicle import Envelope, Input, LLMOutput, LLMRequest, Message, Output, Usage
from chronicle.envelope import genai
from chronicle.envelope.genai import SamplingParams, ToolSchema
from chronicle.session import usage_from


def test_keys_match_the_otel_genai_semantic_conventions():
    attrs = pytest.importorskip("opentelemetry.semconv._incubating.attributes.gen_ai_attributes")
    assert genai.GEN_AI_REQUEST_MODEL == attrs.GEN_AI_REQUEST_MODEL
    assert genai.GEN_AI_REQUEST_TEMPERATURE == attrs.GEN_AI_REQUEST_TEMPERATURE
    assert genai.GEN_AI_REQUEST_TOP_P == attrs.GEN_AI_REQUEST_TOP_P
    assert genai.GEN_AI_REQUEST_MAX_TOKENS == attrs.GEN_AI_REQUEST_MAX_TOKENS
    assert genai.GEN_AI_REQUEST_SEED == attrs.GEN_AI_REQUEST_SEED
    assert genai.GEN_AI_TOOL_DEFINITIONS == attrs.GEN_AI_TOOL_DEFINITIONS
    assert genai.GEN_AI_TOOL_NAME == attrs.GEN_AI_TOOL_NAME
    assert genai.GEN_AI_TOOL_DESCRIPTION == attrs.GEN_AI_TOOL_DESCRIPTION


def test_llm_request_flattens_only_what_is_set():
    assert LLMRequest().to_attributes() == {}
    request = LLMRequest(
        model="gpt-4o",
        sampling=SamplingParams(temperature=0.0, max_tokens=256),
        tools=[ToolSchema(name="t")],
    )
    attrs = request.to_attributes()
    assert attrs["gen_ai.request.model"] == "gpt-4o"
    assert attrs["gen_ai.request.temperature"] == 0.0  # falsy but set: kept
    assert attrs["gen_ai.request.max_tokens"] == 256
    assert "gen_ai.request.top_p" not in attrs
    assert isinstance(attrs["gen_ai.tool.definitions"], str)


def test_llm_request_validates_its_fields():
    with pytest.raises(ValidationError):
        SamplingParams(temperature="hot")
    with pytest.raises(ValidationError):
        LLMRequest(sampling=SamplingParams(max_tokens="many"))


def test_sampling_params_have_no_extra_bag():
    assert list(SamplingParams.model_fields) == ["temperature", "top_p", "max_tokens", "seed"]


def test_attributes_keep_otel_types_through_a_file(tmp_path):
    env = Envelope(
        name="llm",
        kind="llm",
        input=Input(),
        output=Output(),
        attributes={"s": "x", "f": 0.25, "i": 3, "b": True, "l": ["a", "b"], "n": [1, 2]},
    )
    path = tmp_path / "e.json"
    env.write_file(str(path))
    back = Envelope.from_file(str(path))
    assert back.attributes == {"s": "x", "f": 0.25, "i": 3, "b": True, "l": ["a", "b"], "n": [1, 2]}
    assert type(back.attributes["b"]) is bool and type(back.attributes["i"]) is int


def test_record_attributes_keep_primitives_and_stringify_the_rest():
    with chronicle.record("t", attributes={"user": "u1", "turn": 3, "weird": object}) as session:
        pass
    assert session.attributes["user"] == "u1"
    assert session.attributes["turn"] == 3
    assert isinstance(session.attributes["weird"], str)


@pytest.mark.parametrize(
    "payload",
    [
        {"prompt_tokens": 3, "completion_tokens": 2},  # OpenAI
        {"input_tokens": 3, "output_tokens": 2},  # Anthropic
        {"input_tokens": 3.0, "output_tokens": 2.0, "cache_read": 9},  # floats and extras
    ],
)
def test_usage_normalizes_provider_key_names(payload):
    assert usage_from(payload) == Usage(input_tokens=3, output_tokens=2)


def test_usage_ignores_bools_and_missing_counts():
    assert usage_from({"prompt_tokens": True}) is None
    assert usage_from(None) is None
    assert usage_from({}) is None
    assert usage_from({"output_tokens": 4}) == Usage(input_tokens=None, output_tokens=4)


def test_llm_output_is_one_bundle_on_output():
    out = Output(llm=LLMOutput(text="hi", finish_reason="stop", usage=Usage(input_tokens=1)))
    assert list(Output.model_fields) == ["value", "llm"]
    assert list(LLMOutput.model_fields) == ["text", "tool_calls", "finish_reason", "usage"]
    assert out.value is None and out.llm.text == "hi"


def test_message_keeps_provider_extras():
    msg = Message(role="assistant", content="yo", name="bot", tool_calls=[])
    assert msg.model_dump() == {"role": "assistant", "content": "yo", "name": "bot", "tool_calls": []}
