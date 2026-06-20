"""Execution graph built from envelope traces."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from chronicle.envelope.schema import Envelope


@dataclass
class GraphNode:
    envelope: Envelope
    fixture_path: str | None = None
    children: list[str] = field(default_factory=list)


@dataclass
class ExecutionGraph:
    trace_id: str
    nodes: dict[str, GraphNode] = field(default_factory=dict)
    root_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_envelopes(cls, trace_id: str, envelopes: list[Envelope]) -> ExecutionGraph:
        ordered = sorted(envelopes, key=lambda e: e.sequence)
        graph = cls(trace_id=trace_id)
        for envelope in ordered:
            graph.nodes[envelope.envelope_id] = GraphNode(envelope=envelope)
        for envelope in ordered:
            if envelope.parent_envelope_id:
                parent = graph.nodes.get(envelope.parent_envelope_id)
                if parent:
                    parent.children.append(envelope.envelope_id)
            else:
                graph.root_ids.append(envelope.envelope_id)
        return graph

    @classmethod
    def load(cls, directory: str | Path) -> ExecutionGraph:
        root = Path(directory)
        graph_file = root / "graph.json"
        if not graph_file.exists():
            raise FileNotFoundError(f"No graph.json in {root}")

        meta = json.loads(graph_file.read_text())
        trace_id = meta["trace_id"]
        graph = cls(trace_id=trace_id)

        for entry in meta["nodes"]:
            path = root / entry["fixture"]
            envelope = Envelope.from_file(str(path))
            graph.nodes[envelope.envelope_id] = GraphNode(
                envelope=envelope, fixture_path=str(path)
            )

        for edge in meta.get("edges", []):
            parent = graph.nodes.get(edge[0])
            if parent and edge[1] not in parent.children:
                parent.children.append(edge[1])

        graph.root_ids = meta.get("roots", [])
        if not graph.root_ids:
            graph.root_ids = [
                eid
                for eid, node in graph.nodes.items()
                if node.envelope.parent_envelope_id is None
            ]
        return graph

    def save(self, directory: str | Path) -> None:
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)

        ordered = sorted(
            self.nodes.values(), key=lambda n: n.envelope.sequence
        )
        node_entries = []
        edges = []

        for i, node in enumerate(ordered, start=1):
            filename = f"{i:03d}-{node.envelope.node_id}-{node.envelope.invocation_index}.json"
            path = root / filename
            node.envelope.write_file(str(path))
            node.fixture_path = str(path)
            node_entries.append(
                {
                    "envelope_id": node.envelope.envelope_id,
                    "boundary_id": node.envelope.node_id,
                    "boundary_kind": node.envelope.boundary_kind,
                    "invocation_index": node.envelope.invocation_index,
                    "sequence": node.envelope.sequence,
                    "fixture": filename,
                }
            )
            if node.envelope.parent_envelope_id:
                edges.append([node.envelope.parent_envelope_id, node.envelope.envelope_id])

        graph_json = {
            "trace_id": self.trace_id,
            "nodes": node_entries,
            "edges": edges,
            "roots": self.root_ids,
        }
        (root / "graph.json").write_text(json.dumps(graph_json, indent=2))

    def timeline(self) -> list[Envelope]:
        return sorted(
            (n.envelope for n in self.nodes.values()),
            key=lambda e: e.sequence,
        )

    def envelope(self, boundary_id: str, invocation_index: int) -> Envelope:
        matches = [
            n.envelope
            for n in self.nodes.values()
            if n.envelope.node_id == boundary_id
            and n.envelope.invocation_index == invocation_index
        ]
        if not matches:
            raise KeyError(f"No envelope for {boundary_id} invocation {invocation_index}")
        return matches[0]

    def to_mermaid(self) -> str:
        lines = ["graph TD"]
        for node in self.timeline():
            eid = node.envelope_id[:8]
            label = (
                f"{node.node_id}@{node.invocation_index}"
                f"<br/>{node.boundary_kind}"
            )
            if node.action_result.tool_calls:
                tools = ",".join(tc.name for tc in node.action_result.tool_calls)
                label += f"<br/>tools: {tools}"
            elif node.action_result.completion:
                short = node.action_result.completion[:40]
                label += f"<br/>{short}"
            lines.append(f'    {eid}["{label}"]')
            if node.parent_envelope_id:
                pid = node.parent_envelope_id[:8]
                lines.append(f"    {pid} --> {eid}")
        return "\n".join(lines)

    def to_ascii(self) -> str:
        lines = [f"Trace: {self.trace_id}", ""]
        for node in self.timeline():
            indent = "  " if node.parent_envelope_id else ""
            env = node
            action = ""
            if env.action_result.tool_calls:
                tc = env.action_result.tool_calls[0]
                action = f" → tool_call({tc.name})"
            elif env.action_result.raw_response:
                action = f" → {env.action_result.raw_response}"
            elif env.action_result.completion:
                action = f" → {env.action_result.completion[:50]}"
            lines.append(
                f"{indent}[{env.sequence}] {env.node_id}#{env.invocation_index}"
                f" ({env.boundary_kind}){action}"
            )
        return "\n".join(lines)

    @property
    def initial_state(self) -> dict:
        if not self.timeline():
            return {}
        first = self.timeline()[0]
        return dict(first.input_state.graph_state)
