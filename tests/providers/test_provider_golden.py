"""Provider conformance, golden layer: a raw response and its expected canonical form (4.3).

Every supported provider has the same cases (see ``tests/providers/<provider>``): plain text,
text and a tool call in one reply, reasoning, refusal, cached input tokens, a served model that is
missing, and the request input convention. The expected canonical files are authored by hand, not
produced by the adapter, so the test is not circular.

Checks in every case: the canonical result validates as ``LlmOutput``; ``usage`` buckets are
exclusive and additive (their sum equals the provider's own total); ``raw`` is stored unchanged;
``provider``, ``model`` and ``model_source`` are filled.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from agentplane_primitives.enums import FinishReason, ModelSource
from agentplane_primitives.models import LlmInput, LlmOutput, ToolCallBlock

from chronicle.framework.adapters import AnthropicAdapter, LlmAdapter, OpenAiAdapter

HERE = Path(__file__).parent
REQUESTED = {"openai": "gpt-4o", "anthropic": "claude-sonnet-4-5"}
ADAPTERS: dict[str, LlmAdapter] = {
    "openai": OpenAiAdapter("openai"),
    "anthropic": AnthropicAdapter(),
}
CASES = [
    "plain_text",
    "text_and_tool_call",
    "reasoning",
    "refusal",
    "cached_tokens",
    "served_model_missing",
]
PROVIDERS = list(ADAPTERS)


def _load(provider: str, name: str) -> Any:
    return json.loads((HERE / provider / name).read_text(encoding="utf-8"))


def _provider_total(provider: str, raw: dict[str, Any]) -> int:
    usage = raw["usage"]
    if provider == "openai":
        return int(usage["total_tokens"])
    return int(
        usage["input_tokens"]
        + usage["output_tokens"]
        + usage["cache_read_input_tokens"]
        + usage["cache_creation_input_tokens"]
    )


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("case", CASES)
def test_golden_output(provider: str, case: str) -> None:
    raw = _load(provider, f"{case}.raw.json")
    expected = _load(provider, f"{case}.canonical.json")

    output = ADAPTERS[provider].to_canonical_output(raw, REQUESTED[provider])

    assert isinstance(output, LlmOutput)
    assert LlmOutput.model_validate(output.model_dump(mode="json")) == output
    assert output.model_dump(mode="json", exclude={"raw"}) == expected
    assert output.raw == raw  # stored unchanged
    assert output.provider == provider
    assert output.model
    assert output.model_source in (ModelSource.SERVED, ModelSource.REQUESTED)
    assert output.usage is not None
    total = (
        output.usage.input
        + output.usage.cached_read
        + output.usage.cache_write
        + output.usage.output
        + output.usage.reasoning
    )
    assert total == _provider_total(provider, raw)  # exclusive and additive


@pytest.mark.parametrize("provider", PROVIDERS)
def test_served_model_missing_copies_the_requested_model(provider: str) -> None:
    raw = _load(provider, "served_model_missing.raw.json")
    output = ADAPTERS[provider].to_canonical_output(raw, REQUESTED[provider])
    assert output.model == REQUESTED[provider]
    assert output.model_source is ModelSource.REQUESTED


@pytest.mark.parametrize("provider", PROVIDERS)
def test_request_follows_the_input_convention(provider: str) -> None:
    request = _load(provider, "tools_request.json")
    expected = _load(provider, "tools_request.canonical.json")

    llm_input = ADAPTERS[provider].to_canonical_input(request)

    assert isinstance(llm_input, LlmInput)
    assert llm_input.model_dump(mode="json", exclude={"raw"}) == expected
    assert llm_input.raw == request
    # tools: [{name, description?, parameters?}]; tool_choice: auto | none | required | {name}
    assert llm_input.tools is not None
    assert set(llm_input.tools[0]) <= {"name", "description", "parameters"}
    assert llm_input.tool_choice in ("auto", "none", "required") or isinstance(
        llm_input.tool_choice, dict
    )


OPENAI_FINISH = {
    "stop": FinishReason.STOP,
    "length": FinishReason.LENGTH,
    "tool_calls": FinishReason.TOOL_CALLS,
    "content_filter": FinishReason.CONTENT_FILTER,
    "something_new": FinishReason.OTHER,
}
ANTHROPIC_FINISH = {
    "end_turn": FinishReason.STOP,
    "stop_sequence": FinishReason.STOP,
    "max_tokens": FinishReason.LENGTH,
    "tool_use": FinishReason.TOOL_CALLS,
    "refusal": FinishReason.CONTENT_FILTER,
    "pause_turn": FinishReason.OTHER,
    "something_new": FinishReason.OTHER,
}


@pytest.mark.parametrize(("reason", "expected"), OPENAI_FINISH.items())
def test_openai_finish_reason_mapping(reason: str, expected: FinishReason) -> None:
    raw = _load("openai", "plain_text.raw.json")
    raw["choices"][0]["finish_reason"] = reason
    output = ADAPTERS["openai"].to_canonical_output(raw, "gpt-4o")
    assert output.finish_reason is expected
    assert output.raw == raw  # the original value stays in raw
    assert raw["choices"][0]["finish_reason"] == reason


@pytest.mark.parametrize(("reason", "expected"), ANTHROPIC_FINISH.items())
def test_anthropic_finish_reason_mapping(reason: str, expected: FinishReason) -> None:
    raw = _load("anthropic", "plain_text.raw.json")
    raw["stop_reason"] = reason
    output = ADAPTERS["anthropic"].to_canonical_output(raw, "claude-sonnet-4-5")
    assert output.finish_reason is expected
    assert output.raw == raw
    assert raw["stop_reason"] == reason


def test_openai_tool_call_arguments_that_are_not_json_are_kept() -> None:
    raw = _load("openai", "text_and_tool_call.raw.json")
    raw["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = "{not json"
    output = ADAPTERS["openai"].to_canonical_output(raw, "gpt-4o")
    call = output.content[1]
    assert isinstance(call, ToolCallBlock)
    assert call.arguments == {"$raw_arguments": "{not json"}


def test_a_response_with_no_usage_has_null_usage() -> None:
    raw = _load("openai", "plain_text.raw.json")
    del raw["usage"]
    assert ADAPTERS["openai"].to_canonical_output(raw, "gpt-4o").usage is None
