"""Print a saved trace as a tree: spans, the envelopes in each, and the calls between agents."""

import json
from typing import Any

from _support.plane import LocalPlane


def _summary(envelope: dict[str, Any]) -> str:
    kind = envelope["kind"]
    output = envelope.get("output") or {}
    if kind == "llm":
        usage = output.get("usage") or {}
        model = output.get("model", "?")
        tokens = f"{usage.get('input', 0)} in / {usage.get('output', 0)} out"
        reason = output.get("finish_reason", "")
        return f"{model}  {tokens}  {reason}"
    raw_in = (envelope.get("input") or {}).get("raw")
    text = json.dumps(raw_in, default=str)
    return text if len(text) <= 70 else text[:67] + "..."


def show_trace(plane: LocalPlane, trace_id: str) -> None:
    """Print the trace, its spans and every envelope, nesting a callee span under the call."""
    trace = plane.get(f"/v1/traces/{trace_id}")
    spans = trace["spans"]
    children: dict[str, list[dict[str, Any]]] = {}
    for span in spans:
        if span.get("parent_envelope_id"):
            children.setdefault(span["parent_envelope_id"], []).append(span)
    roots = [s for s in spans if not s.get("parent_envelope_id")]

    print(f"trace {trace_id}  state={trace['state']}  spans={len(spans)}")

    def walk(span: dict[str, Any], depth: int) -> None:
        pad = "  " * depth
        print(f"{pad}span {span['span_id']}  service={span['service']}  status={span['status']}")
        envelopes = plane.get(f"/v1/traces/{trace_id}/spans/{span['span_id']}/envelopes")
        ordered = sorted(
            envelopes["envelopes"], key=lambda e: e["metadata"].get("chronicle.sequence", 0)
        )
        for envelope in ordered:
            seq = envelope["metadata"].get("chronicle.sequence", "?")
            line = f"{pad}  #{seq} {envelope['kind']:<4} {envelope['name']}"
            print(f"{line:<52} {_summary(envelope)}")
            for child in children.get(envelope["envelope_id"], []):
                walk(child, depth + 2)

    for root in roots:
        walk(root, 0)
