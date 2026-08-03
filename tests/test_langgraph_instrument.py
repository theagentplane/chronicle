"""chronicle.instrument(graph) auto-instruments every LangGraph node and every
add_conditional_edges routing function in one call — sync, async, whether
called before or after .compile(), and idempotently. See issue #22."""

from __future__ import annotations

import asyncio
from typing import TypedDict

import pytest
from langgraph.graph import END, StateGraph

import chronicle


class State(TypedDict):
    x: int
    path: list[str]


def _build_graph() -> StateGraph:
    def step_a(state: State) -> dict:
        return {"x": state["x"] + 1, "path": [*state["path"], "a"]}

    def step_b(state: State) -> dict:
        return {"x": state["x"] + 10, "path": [*state["path"], "b"]}

    def route(state: State) -> str:
        return "b" if state["x"] > 0 else END

    graph = StateGraph(State)
    graph.add_node("a", step_a)
    graph.add_node("b", step_b)
    graph.set_entry_point("a")
    graph.add_conditional_edges("a", route, {"b": "b", END: END})
    graph.add_edge("b", END)
    return graph


@pytest.mark.layer1
def test_instrument_records_nodes_and_router_decision():
    session = chronicle.reset_session()
    session.begin_trace("t-instrument")

    app = chronicle.instrument(_build_graph()).compile()
    result = app.invoke({"x": 1, "path": []})

    assert result["path"] == ["a", "b"]
    node_ids = {e.node_id for e in session._recorded_envelopes}
    assert node_ids == {"a", "a:route", "b"}

    router_env = next(e for e in session._recorded_envelopes if e.node_id == "a:route")
    assert router_env.boundary_kind == "router"
    assert router_env.action_result.completion == "b"


@pytest.mark.layer1
def test_instrument_after_compile_still_reroutes_execution():
    """Instrumenting late (after .compile()) must still record — the compiled
    graph keeps a live reference to the builder this mutates in place."""
    session = chronicle.reset_session()
    session.begin_trace("t-late")

    compiled = _build_graph().compile()
    chronicle.instrument(compiled)
    compiled.invoke({"x": 1, "path": []})

    assert len(session._recorded_envelopes) == 3


@pytest.mark.layer1
def test_instrument_records_through_async_invocation():
    """A sync node's auto-generated executor shim must be rebuilt around the
    wrapped function, not left pointing at the original — otherwise ainvoke
    silently skips recording."""
    session = chronicle.reset_session()
    session.begin_trace("t-async")

    app = chronicle.instrument(_build_graph()).compile()
    result = asyncio.run(app.ainvoke({"x": 1, "path": []}))

    assert result["path"] == ["a", "b"]
    assert len(session._recorded_envelopes) == 3


@pytest.mark.layer1
def test_instrument_is_idempotent():
    graph = _build_graph()
    chronicle.instrument(graph)
    chronicle.instrument(graph)  # calling twice must not double-wrap
    app = graph.compile()

    session = chronicle.reset_session()
    session.begin_trace("t-idempotent")
    app.invoke({"x": 1, "path": []})

    assert len(session._recorded_envelopes) == 3


@pytest.mark.layer1
def test_replay_stubs_the_router_without_calling_the_route_function(tmp_path):
    """Layer 1 replay must reproduce which branch was taken from the fixture,
    never by actually running the routing function again."""
    trace = tmp_path / "trace"
    with chronicle.record("incident", export=str(trace)):
        app = chronicle.instrument(_build_graph()).compile()
        app.invoke({"x": 1, "path": []})

    calls: list[State] = []

    def spy_route(state: State) -> str:
        calls.append(state)
        return "b"

    graph = _build_graph()
    graph.branches["a"]["route"].path.func = spy_route

    with chronicle.replay_trace(str(trace)):
        app = chronicle.instrument(graph).compile()
        result = app.invoke({"x": 1, "path": []})

    assert calls == []  # the router was stubbed, never executed live
    assert result["path"] == ["a", "b"]
