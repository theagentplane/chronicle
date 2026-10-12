"""Topology 1 and 2: a chain of two agents over A2A and over plain HTTP, per framework."""

import pytest
from agentplane_primitives.models import LlmOutput

from tests.e2e.agents.factory import ANTHROPIC_WIRE, FRAMEWORKS
from tests.e2e.assertions import (
    assert_cost_fields,
    assert_linked,
    assert_no_traceparent_sent_to_provider,
    assert_well_formed_trace,
    llm_envelopes,
    outbound_call,
    tool_raw_input,
    tool_raw_output,
)
from tests.e2e.scripts import delegate_then_answer, final
from tests.e2e.system import System

PROVIDER = {"anthropic_sdk": "anthropic"}


@pytest.mark.parametrize("transport", ["a2a", "http"])
@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_chain_of_two_agents(system: System, framework: str, transport: str) -> None:
    specialist = system.add(
        "specialist",
        "handrolled",
        [final("handrolled", "the capital is Paris")],
        transport=transport,
    )
    orchestrator = system.add(
        "orchestrator",
        framework,
        delegate_then_answer(
            framework, "ask_specialist", "capital of France?", "The answer is Paris."
        ),
        tools=[specialist.peer_tool("ask_specialist")],
    )
    system.configure()

    response = system.call("orchestrator", "What is the capital of France?")

    assert response.status_code == 200
    assert response.json() == {"answer": "The answer is Paris."}
    assert_well_formed_trace(system, ["orchestrator", "specialist"])

    # the downstream span hangs off the caller's outbound call envelope
    suffix = "/rpc" if transport == "a2a" else "/run"
    assert_linked(system, "orchestrator", "specialist", suffix)
    outbound = outbound_call(system, "orchestrator", suffix)
    assert outbound.name.startswith("http POST 127.0.0.1:")
    assert tool_raw_input(outbound)["method"] == "POST"
    assert tool_raw_output(outbound)["status_code"] == 200  # type: ignore[index]

    # cost fields are filled the same way whatever the framework
    (llm_a, llm_b) = llm_envelopes(system, "orchestrator")
    for envelope in (llm_a, llm_b):
        assert_cost_fields(envelope, PROVIDER.get(framework, "openai"))
    (specialist_llm,) = llm_envelopes(system, "specialist")
    assert_cost_fields(specialist_llm, "openai")

    # nothing leaks to the provider; the peer received the header (it joined the trace above)
    assert_no_traceparent_sent_to_provider(orchestrator.llm, specialist.llm)
    assert framework in ANTHROPIC_WIRE or llm_a.input.raw["model"] == "gpt-4o"


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_cached_tokens_are_bucketed_the_same_for_every_framework(
    system: System, framework: str
) -> None:
    """OpenAI counts cached tokens inside the prompt, Anthropic reports them separately; the
    adapters convert both into the same exclusive, additive buckets."""
    if framework in ANTHROPIC_WIRE:
        reply = final(framework, "done", input_tokens=24, output_tokens=5, cache_read=16)
    else:
        reply = final(framework, "done", prompt=40, completion=5, cached=16)
    system.add("solo", framework, [reply])
    system.configure()

    assert system.call("solo", "hi").json() == {"answer": "done"}

    (llm,) = llm_envelopes(system, "solo")
    assert isinstance(llm.output, LlmOutput)
    assert llm.output.usage is not None
    assert (llm.output.usage.input, llm.output.usage.cached_read, llm.output.usage.output) == (
        24,
        16,
        5,
    )
