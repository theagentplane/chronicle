#!/usr/bin/env python3
"""Render a recorded Chronicle trace as an execution graph."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from chronicle.execution_graph import ExecutionGraph
from chronicle.visualizer import open_trace_ui, write_trace_html

DEFAULT_TRACE = ROOT / "fixtures" / "traces" / "deletion-incident-001"


def main() -> None:
    parser = argparse.ArgumentParser(description="Visualize a Chronicle execution trace")
    parser.add_argument(
        "trace_dir",
        nargs="?",
        default=str(DEFAULT_TRACE),
        help="Path to trace directory containing graph.json",
    )
    parser.add_argument(
        "--ui",
        action="store_true",
        help="Open interactive HTML visualization in browser",
    )
    parser.add_argument("--port", type=int, default=8765, help="UI server port")
    parser.add_argument(
        "--html",
        metavar="PATH",
        help="Write static HTML file (e.g. trace.html)",
    )
    args = parser.parse_args()

    trace_dir = Path(args.trace_dir)
    if not trace_dir.exists():
        print(f"No trace found at {trace_dir}")
        print("Run: python examples/deletion_agent/record_incident.py")
        sys.exit(1)

    graph = ExecutionGraph.load(trace_dir)

    if args.ui:
        if args.html:
            write_trace_html(graph, args.html)
        open_trace_ui(trace_dir, port=args.port, open_browser=True)
        return

    if args.html:
        path = write_trace_html(graph, args.html)
        print(f"Wrote {path}")
        return

    print("=" * 60)
    print("CHRONICLE EXECUTION GRAPH")
    print("=" * 60)
    print()
    print(graph.to_ascii())
    print()
    print("Tip: python examples/deletion_agent/show_trace.py --ui")
    print()
    print("-" * 60)
    print("MERMAID (paste into mermaid.live)")
    print("-" * 60)
    print(graph.to_mermaid())
    print()
    print("-" * 60)
    print("TIMELINE DETAIL")
    print("-" * 60)
    for env in graph.timeline():
        print(f"\n[{env.sequence}] {env.node_id}#{env.invocation_index} ({env.boundary_kind})")
        print(f"  envelope_id: {env.envelope_id}")
        if env.parent_envelope_id:
            print(f"  parent:      {env.parent_envelope_id}")
        print(f"  input:       {env.input_state.graph_state.get('environment', env.input_state.messages)}")
        if env.action_result.tool_calls:
            for tc in env.action_result.tool_calls:
                print(f"  tool_call:   {tc.name}({tc.arguments})")
        if env.action_result.raw_response:
            print(f"  result:      {env.action_result.raw_response}")
        elif env.action_result.completion:
            print(f"  completion:  {env.action_result.completion}")


if __name__ == "__main__":
    main()
