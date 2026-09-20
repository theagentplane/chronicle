"""Tests for execution graph rendering and loading."""

from pathlib import Path

from chronicle.execution_graph import ExecutionGraph
from chronicle.ids import is_span_id, is_trace_id

TRACE_DIR = Path(__file__).parent.parent / "fixtures" / "traces" / "deletion-incident-001"


def test_execution_graph_loads_trace():
    graph = ExecutionGraph.load(TRACE_DIR)
    assert is_trace_id(graph.trace_id)
    assert graph.dims["chronicle.trace.name"] == "trace-deletion-incident-001"
    assert len(graph.timeline()) == 3


def test_execution_graph_sequential_boundaries_are_sibling_roots():
    """Boundaries that run one after another (not nested) are all roots."""
    graph = ExecutionGraph.load(TRACE_DIR)
    timeline = graph.timeline()
    assert [e.node_id for e in timeline] == ["agent", "delete_file", "agent"]
    assert all(e.parent_envelope_id is None for e in timeline)
    assert graph.root_ids == [e.envelope_id for e in timeline]
    assert all(is_span_id(e.envelope_id) for e in timeline)
    assert {e.trace_id for e in timeline} == {graph.trace_id}


def test_execution_graph_mermaid():
    graph = ExecutionGraph.load(TRACE_DIR)
    mermaid = graph.to_mermaid()
    assert "agent@1" in mermaid
    assert "delete_file@1" in mermaid
    assert "agent@2" in mermaid


def test_parent_calls_same_subagent_twice_waterfall():
    """Same sub-agent twice under one parent; each has nested llm + tool spans."""
    graph = ExecutionGraph.load(
        Path(__file__).parent.parent
        / "fixtures"
        / "traces"
        / "parent-calls-subagent-twice"
    )
    timeline = graph.timeline()
    orch = next(e for e in timeline if e.node_id == "orchestrator")
    researchers = [e for e in timeline if e.parent_envelope_id == orch.envelope_id]
    assert [(e.node_id, e.invocation_index) for e in researchers] == [
        ("researcher", 1),
        ("researcher", 2),
    ]
    for r in researchers:
        kids = sorted(
            (e for e in timeline if e.parent_envelope_id == r.envelope_id),
            key=lambda e: e.sequence,
        )
        assert [e.boundary_kind for e in kids] == ["llm", "tool"]
        assert [e.node_id for e in kids] == ["llm", "web_search"]

    tree = graph.to_otel_tree()
    assert "orchestrator#1" in tree
    assert "researcher#1" in tree
    assert "researcher#2" in tree
    assert "llm#1" in tree and "llm#2" in tree
    assert "web_search#1" in tree and "web_search#2" in tree
    waterfall = graph.to_otel_waterfall()
    assert "█" in waterfall
    assert "llm#1" in waterfall and "web_search#2" in waterfall
