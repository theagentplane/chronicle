"""Topology 3 and 4: fan-out, and three hops across different frameworks and providers."""

from tests.e2e.assertions import (
    assert_cost_fields,
    assert_linked,
    assert_no_traceparent_sent_to_provider,
    assert_well_formed_trace,
    envelopes,
    llm_envelopes,
    outbound_call,
    span_of,
)
from tests.e2e.scripts import call_tools, delegate_then_answer, final
from tests.e2e.system import System


def test_fan_out_to_two_specialists(system: System) -> None:
    alpha = system.add("alpha", "handrolled", [final("handrolled", "alpha says 1")])
    beta = system.add("beta", "anthropic_sdk", [final("anthropic_sdk", "beta says 2")])
    orchestrator = system.add(
        "orchestrator",
        "openai_sdk",
        [
            call_tools(
                "openai_sdk",
                [("ask_alpha", {"task": "do a"}), ("ask_beta", {"task": "do b"})],
            ),
            final("openai_sdk", "alpha says 1 and beta says 2"),
        ],
        tools=[alpha.peer_tool("ask_alpha"), beta.peer_tool("ask_beta")],
    )
    system.configure()

    response = system.call("orchestrator", "run both")

    assert response.json() == {"answer": "alpha says 1 and beta says 2"}
    assert_well_formed_trace(system, ["orchestrator", "alpha", "beta"])
    # two outbound calls, each its own envelope, each parent of exactly one downstream span
    outbound = [e for e in envelopes(system, "orchestrator") if e.name.startswith("http POST")]
    assert len(outbound) == 2
    parents = {
        span_of(system, "alpha").parent_envelope_id,
        span_of(system, "beta").parent_envelope_id,
    }
    assert parents == {e.envelope_id for e in outbound}
    # the two calls are siblings under their tool envelopes in the same span
    assert len({e.span_id for e in outbound}) == 1
    assert_no_traceparent_sent_to_provider(orchestrator.llm, alpha.llm, beta.llm)


def test_three_hops_mixed_frameworks_providers_and_transports(system: System) -> None:
    leaf = system.add(
        "leaf",
        "anthropic_sdk",
        [final("anthropic_sdk", "leaf result")],
        transport="http",
    )
    middle = system.add(
        "middle",
        "handrolled",
        delegate_then_answer("handrolled", "ask_leaf", "go deeper", "middle saw: leaf result"),
        transport="a2a",
        tools=[leaf.peer_tool("ask_leaf")],
        provider="litellm",
    )
    orchestrator = system.add(
        "orchestrator",
        "langgraph",
        delegate_then_answer("langgraph", "ask_middle", "start", "done: middle saw: leaf result"),
        tools=[middle.peer_tool("ask_middle")],
    )
    system.configure()

    response = system.call("orchestrator", "three hops please")

    assert response.json() == {"answer": "done: middle saw: leaf result"}
    assert_well_formed_trace(system, ["orchestrator", "middle", "leaf"])
    assert_linked(system, "orchestrator", "middle", "/rpc")  # A2A hop
    assert_linked(system, "middle", "leaf", "/run")  # plain HTTP hop

    # nothing in Chronicle depends on the framework or the provider: same fields, three providers
    for service, provider in (
        ("orchestrator", "openai"),
        ("middle", "litellm"),
        ("leaf", "anthropic"),
    ):
        for envelope in llm_envelopes(system, service):
            assert_cost_fields(envelope, provider)
    assert_no_traceparent_sent_to_provider(orchestrator.llm, middle.llm, leaf.llm)

    # LangGraph: the nodes and the routing decision were recorded as tool boundaries
    names = {e.name for e in envelopes(system, "orchestrator")}
    assert {"agent", "tools"} <= names
    assert any(name.startswith("agent:") for name in names)
    assert outbound_call(system, "middle", "/run")
