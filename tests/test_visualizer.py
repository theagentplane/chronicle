"""Tests for trace visualization HTML."""

from pathlib import Path

from chronicle.execution_graph import ExecutionGraph
from chronicle.visualizer import render_trace_html, write_trace_html

TRACE_DIR = Path(__file__).parent.parent / "fixtures" / "traces" / "deletion-incident-001"


def test_render_trace_html_contains_trace_and_nodes():
    graph = ExecutionGraph.load(TRACE_DIR)
    html = render_trace_html(graph)
    assert "trace-deletion-incident-001" in html
    assert "full_envelope" in html
    assert "schema_version" in html
    assert "delete_file" in html
    assert "mermaid" in html
    assert "selectByShortId" in html


def test_write_trace_html(tmp_path):
    graph = ExecutionGraph.load(TRACE_DIR)
    path = write_trace_html(graph, tmp_path / "trace.html")
    assert path.exists()
    content = path.read_text()
    assert len(content) > 1000
