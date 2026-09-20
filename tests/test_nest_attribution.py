"""OTel-style nest parents + flat dims — boundaries on nodes, not the full agent."""

from __future__ import annotations

from chronicle import ExecutionGraph, boundary, record, wrap_llm
from chronicle.envelope.schema import InputState


def test_nested_boundaries_parent_to_active_span():
    """Child spans parent to the open outer boundary, not the last finished one."""

    @boundary("outer", kind="custom")
    def outer() -> str:
        return inner()

    @boundary("inner", kind="custom")
    def inner() -> str:
        return "ok"

    with record("nest-demo", attributes={"session_id": "s1", "user_id": "u1"}) as session:
        assert outer() == "ok"

    envelopes = session.envelopes
    assert len(envelopes) == 2
    by_name = {e.name: e for e in envelopes}
    assert by_name["inner"].parent_envelope_id == by_name["outer"].envelope_id
    assert by_name["outer"].parent_envelope_id is None
    assert by_name["inner"].attributes["session_id"] == "s1"
    assert by_name["outer"].attributes["user_id"] == "u1"


def test_sibling_roots_when_not_nested():
    @boundary("a", kind="custom")
    def a() -> str:
        return "a"

    @boundary("b", kind="custom")
    def b() -> str:
        return "b"

    with record("siblings") as session:
        a()
        b()

    assert all(e.parent_envelope_id is None for e in session.envelopes)


def test_boundaries_on_decision_nodes_not_full_agent():
    """Client pattern: @boundary on llm/tool nodes; orchestration is plain code."""

    @boundary("planner", kind="llm")
    def planner(task: str) -> dict:
        return {
            "completion": None,
            "model": "stub-planner",
            "finish_reason": "tool_calls",
            "tool_calls": [{"id": "c1", "name": "web_search", "arguments": {"q": task}}],
        }

    @boundary("web_search", kind="tool")
    def web_search(q: str) -> dict:
        return {"results": [f"doc:{q}"], "q": q}

    @boundary("summarizer", kind="llm")
    def summarizer(hits: list[str]) -> dict:
        return {"completion": f"summary of {hits[0]}", "model": "stub-summarizer"}

    # No @boundary on the full agent — just wire the nodes.
    def run_agent(task: str) -> str:
        plan = planner(task)
        tool = plan["tool_calls"][0]
        hits = web_search(**tool["arguments"])
        out = summarizer(hits["results"])
        return out["completion"]

    with record(
        "nodes-only",
        attributes={"session_id": "sess_1", "message_id": "msg_9"},
    ) as session:
        assert "summary of doc:vendors" in run_agent("vendors")

    envelopes = session.envelopes
    assert [e.name for e in envelopes] == ["planner", "web_search", "summarizer"]
    assert [e.kind for e in envelopes] == ["llm", "tool", "llm"]
    # Sequential top-level nodes → sibling roots (no fake "agent" parent span).
    assert all(e.parent_envelope_id is None for e in envelopes)
    assert all(e.attributes["session_id"] == "sess_1" for e in envelopes)

    tree = ExecutionGraph.from_envelopes(session.trace_id, envelopes).to_otel_tree()
    assert "planner#1" in tree and "web_search#1" in tree and "summarizer#1" in tree
    assert "agent#" not in tree


def test_graph_node_nests_llm_and_tool_children():
    """LangGraph-style node span: llm + tool called inside parent to that node."""

    @boundary("llm", kind="llm")
    def call_llm(messages):
        q = messages[-1]["content"]
        return {
            "completion": None,
            "model": "stub-researcher",
            "finish_reason": "tool_calls",
            "tool_calls": [{"id": "c1", "name": "web_search", "arguments": {"q": q}}],
        }

    @boundary("web_search", kind="tool")
    def web_search(q: str) -> dict:
        return {"results": [f"doc:{q}"]}

    @boundary("researcher", kind="custom")  # graph node, not "the whole agent"
    def researcher_node(query: str) -> str:
        decision = call_llm([{"role": "user", "content": query}])
        hit = web_search(**decision["tool_calls"][0]["arguments"])
        return hit["results"][0]

    # Plain orchestrator: calls the same node twice — no full-agent boundary.
    def run(task: str) -> list[str]:
        return [researcher_node("pricing"), researcher_node("risks")]

    with record("graph-node-nest", attributes={"session_id": "s2"}) as session:
        assert run("compare") == ["doc:pricing", "doc:risks"]

    researchers = [e for e in session.envelopes if e.name == "researcher"]
    assert len(researchers) == 2
    assert all(r.parent_envelope_id is None for r in researchers)

    for r in researchers:
        kids = sorted(
            (e for e in session.envelopes if e.parent_envelope_id == r.envelope_id),
            key=lambda e: e.sequence,
        )
        assert [e.name for e in kids] == ["llm", "web_search"]
        assert [e.kind for e in kids] == ["llm", "tool"]
        assert kids[0].parent_envelope_id == r.envelope_id
        assert kids[1].parent_envelope_id == r.envelope_id

    waterfall = ExecutionGraph.from_envelopes(
        session.trace_id, session.envelopes
    ).to_otel_waterfall()
    assert "researcher#1" in waterfall and "researcher#2" in waterfall
    assert "llm#1" in waterfall and "web_search#2" in waterfall


def test_wrap_llm_nests_under_graph_node():
    def dispatch(messages, **kwargs):
        return {"content": "hi", "model": "stub-model"}

    llm = wrap_llm(
        "llm",
        dispatch,
        extract_input=lambda messages, **kw: InputState(messages=list(messages)),
        extract_result=lambda r: r,
    )

    @boundary("researcher", kind="custom")
    def researcher_node() -> str:
        return llm([{"role": "user", "content": "hi"}])["content"]

    with record("wrap-nest", attributes={"message_id": "m9"}) as session:
        assert researcher_node() == "hi"

    by_name = {e.name: e for e in session.envelopes}
    assert by_name["llm"].parent_envelope_id == by_name["researcher"].envelope_id
    assert by_name["llm"].attributes.get("model_version") == "stub-model"
    assert by_name["llm"].attributes["message_id"] == "m9"
