"""Execution graph built from envelope traces."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
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
            filename = f"{i:03d}-{node.envelope.name}-{node.envelope.invocation_index}.json"
            path = root / filename
            node.envelope.write_file(str(path))
            node.fixture_path = str(path)
            node_entries.append(
                {
                    "envelope_id": node.envelope.envelope_id,
                    "name": node.envelope.name,
                    "kind": node.envelope.kind,
                    "invocation_index": node.envelope.invocation_index,
                    "sequence": node.envelope.sequence,
                    "fixture": filename,
                }
            )
            if node.envelope.parent_envelope_id:
                edges.append([node.envelope.parent_envelope_id, node.envelope.envelope_id])

        graph_json = {
            "trace_id": self.trace_id,
            "attributes": self.attributes,
            "spans": node_entries,  # OTel name; ``nodes`` kept for back-compat
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
            if n.envelope.name == boundary_id
            and n.envelope.invocation_index == invocation_index
        ]
        if not matches:
            raise KeyError(f"No envelope for {boundary_id} invocation {invocation_index}")
        return matches[0]

    @property
    def attributes(self) -> dict[str, str]:
        """Trace-level attributes: keys shared by every span (minus span-only ones)."""
        timelines = self.timeline()
        if not timelines:
            return {}
        shared = dict(timelines[0].attributes)
        for env in timelines[1:]:
            shared = {k: v for k, v in shared.items() if env.attributes.get(k) == v}
        for key in ("model_version", "error.type"):
            shared.pop(key, None)
        return shared

    def to_mermaid(self) -> str:
        lines = ["graph TD"]
        for node in self.timeline():
            eid = node.envelope_id[:8]
            label = (
                f"{node.name}@{node.invocation_index}"
                f"<br/>{node.kind}"
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
        """OTel-style nested span tree (trace_id / span_id / parent_span_id)."""
        return self.to_otel_tree()

    def to_otel_tree(self) -> str:
        """Render the run as an OpenTelemetry-style Trace → Spans tree."""
        lines = [f"Trace: {self.trace_id}"]
        trace_attrs = self.attributes
        if trace_attrs:
            dim_str = " ".join(f"{k}={v}" for k, v in sorted(trace_attrs.items()))
            lines.append(f"  resource/attributes: {dim_str}")
        lines.append("")

        children: dict[str | None, list[Envelope]] = {}
        for env in self.timeline():
            children.setdefault(env.parent_envelope_id, []).append(env)

        def walk(parent_key: str | None, prefix: str) -> None:
            siblings = children.get(parent_key, [])
            for i, env in enumerate(siblings):
                last = i == len(siblings) - 1
                branch = "└─" if last else "├─"
                child_prefix = f"{prefix}{'   ' if last else '│  '}"
                span_short = env.span_id[:8]
                parent_short = env.parent_span_id[:8] if env.parent_span_id else "—"
                lines.append(
                    f"{prefix}{branch} {env.name}#{env.invocation_index} "
                    f"({env.kind})  span={span_short} parent={parent_short}"
                )
                span_attrs = {
                    k: v
                    for k, v in env.attributes.items()
                    if k not in trace_attrs
                }
                if span_attrs:
                    dim_str = " ".join(f"{k}={v}" for k, v in sorted(span_attrs.items()))
                    lines.append(f"{child_prefix}attrs: {dim_str}")
                walk(env.envelope_id, child_prefix)

        if None in children or not self.timeline():
            walk(None, "")
        else:
            # Orphan parents: flat fallback.
            for env in self.timeline():
                parent_short = (env.parent_span_id or "—")[:8]
                lines.append(
                    f"- {env.name}#{env.invocation_index} ({env.kind})  "
                    f"span={env.span_id[:8]} parent={parent_short}"
                )

        return "\n".join(lines)

    def to_otel_waterfall(self, *, width: int = 48) -> str:
        """Render an OpenTelemetry-style timeline waterfall (nested bars over time).

        Each row is a span; indentation follows parent→child. The bar covers
        ``start_time`` → ``end_time``. Missing ``start_time`` falls back
        to reconstructing from children / end time.
        """
        envelopes = self.timeline()
        if not envelopes:
            return f"Trace: {self.trace_id}\n(no spans)"

        # Resolve [start, end] per span. Parent opens before children and closes after.
        intervals: dict[str, tuple[datetime, datetime]] = {}
        for env in envelopes:
            end = env.end_time
            start = env.start_time or end
            intervals[env.envelope_id] = (start, end)

        # Expand parents to enclose children (OTel parent fully wraps nested work).
        children: dict[str | None, list[Envelope]] = {}
        for env in envelopes:
            children.setdefault(env.parent_envelope_id, []).append(env)

        def enclose(eid: str) -> tuple[datetime, datetime]:
            start, end = intervals[eid]
            for child in children.get(eid, []):
                c_start, c_end = enclose(child.envelope_id)
                if c_start < start:
                    start = c_start
                if c_end > end:
                    end = c_end
            intervals[eid] = (start, end)
            return start, end

        for root in children.get(None, []):
            enclose(root.envelope_id)

        t0 = min(s for s, _ in intervals.values())
        t1 = max(e for _, e in intervals.values())
        total_ms = max((t1 - t0).total_seconds() * 1000.0, 1.0)

        def col(dt: datetime) -> int:
            ms = (dt - t0).total_seconds() * 1000.0
            return max(0, min(width - 1, int(round(ms / total_ms * (width - 1)))))

        lines = [
            f"Trace: {self.trace_id}",
            f"  total: {total_ms:.1f}ms   [0ms ──► {total_ms:.1f}ms]",
        ]
        trace_attrs = self.attributes
        if trace_attrs:
            dim_str = " ".join(f"{k}={v}" for k, v in sorted(trace_attrs.items()))
            lines.append(f"  resource/attributes: {dim_str}")
        lines.append("")
        label_w = max(
            (len(f"{e.name}#{e.invocation_index}") + depth * 2 for depth, e in
             self._waterfall_rows(children)),
            default=12,
        )
        label_w = min(max(label_w, 16), 28)

        def render(parent_key: str | None, depth: int) -> None:
            for env in children.get(parent_key, []):
                start, end = intervals[env.envelope_id]
                left = col(start)
                right = col(end)
                if right <= left:
                    right = min(width, left + 1)
                bar = " " * left + "█" * (right - left)
                bar = bar.ljust(width)
                dur_ms = (end - start).total_seconds() * 1000.0
                name = f"{'  ' * depth}{env.name}#{env.invocation_index}"
                lines.append(
                    f"{name:<{label_w}} {bar}  {dur_ms:6.1f}ms  {env.kind}"
                )
                render(env.envelope_id, depth + 1)

        render(None, 0)
        # Time axis
        lines.append(f"{'':<{label_w}} {'└' + '─' * (width - 2) + '┘'}")
        lines.append(f"{'':<{label_w}} 0ms{' ' * (width - 10)}{total_ms:.0f}ms")
        return "\n".join(lines)

    def _waterfall_rows(
        self, children: dict[str | None, list[Envelope]]
    ):
        def walk(parent_key: str | None, depth: int):
            for env in children.get(parent_key, []):
                yield depth, env
                yield from walk(env.envelope_id, depth + 1)

        yield from walk(None, 0)

    @property
    def initial_state(self) -> dict:
        if not self.timeline():
            return {}
        first = self.timeline()[0]
        return dict(first.input_state.graph_state)
