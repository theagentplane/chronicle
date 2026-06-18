"""Tests for execution graph rendering and loading."""

from pathlib import Path

from chronicle.execution_graph import ExecutionGraph

TRACE_DIR = Path(__file__).parent.parent / "fixtures" / "traces" / "deletion-incident-001"


def test_execution_graph_loads_trace():
    graph = ExecutionGraph.load(TRACE_DIR)
    assert graph.trace_id == "trace-deletion-incident-001"
    assert len(graph.timeline()) == 3


def test_execution_graph_parent_chain():
    graph = ExecutionGraph.load(TRACE_DIR)
    timeline = graph.timeline()
    assert timeline[0].node_id == "agent"
    assert timeline[1].node_id == "delete_file"
    assert timeline[1].parent_envelope_id == timeline[0].envelope_id
    assert timeline[2].parent_envelope_id == timeline[1].envelope_id


def test_execution_graph_mermaid():
    graph = ExecutionGraph.load(TRACE_DIR)
    mermaid = graph.to_mermaid()
    assert "agent@1" in mermaid
    assert "delete_file@1" in mermaid
    assert "-->" in mermaid
