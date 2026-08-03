"""chronicle.instrument(graph): one call records every node AND every
add_conditional_edges routing decision on a compiled LangGraph graph.

Run:
    pip install -e ".[dev]"
    python examples/langgraph_demo/routing_demo.py
"""

from __future__ import annotations

from typing import TypedDict

import chronicle

try:
    from langgraph.graph import END, StateGraph
except ImportError:
    print("Install langgraph: pip install chronicle[langgraph]")
    raise


class AgentState(TypedDict):
    query: str
    needs_search: bool
    completion: str


def agent_node(state: AgentState) -> dict:
    needs_search = "reset" in state["query"].lower()
    return {"needs_search": needs_search}


def search_node(state: AgentState) -> dict:
    return {"completion": "You can reset your API key from Settings > API Keys."}


def answer_node(state: AgentState) -> dict:
    return {"completion": "I can help — could you say more about what you need?"}


def route_after_agent(state: AgentState) -> str:
    return "search" if state["needs_search"] else "answer"


def build_app():
    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("search", search_node)
    graph.add_node("answer", answer_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges(
        "agent", route_after_agent, {"search": "search", "answer": "answer"}
    )
    graph.add_edge("search", END)
    graph.add_edge("answer", END)

    # One call: every node above, plus route_after_agent's decision, is now a
    # Chronicle boundary — recorded live, and stub-replayable from a fixture.
    return chronicle.instrument(graph).compile()


def main() -> None:
    app = build_app()

    trace_dir = "fixtures/traces/langgraph-routing-demo"
    with chronicle.record("langgraph-routing-demo", export=trace_dir) as session:
        result = app.invoke({"query": "How do I reset my API key?", "needs_search": False, "completion": ""})

    print(f"Completion: {result['completion']}")
    print(f"Recorded {len(session._recorded_envelopes)} envelope(s) to {trace_dir}/")
    for e in session._recorded_envelopes:
        print(f"  node={e.node_id}  kind={e.boundary_kind}  completion={e.action_result.completion!r}")

    # Replay: no node function and no routing function runs — every crossing,
    # including which branch was taken, comes back from the fixture.
    with chronicle.replay_trace(trace_dir) as session:
        replayed = app.invoke({"query": "How do I reset my API key?", "needs_search": False, "completion": ""})
    assert replayed["completion"] == result["completion"]
    print("Replay reproduced the same completion with no node/router code executed.")


if __name__ == "__main__":
    main()
