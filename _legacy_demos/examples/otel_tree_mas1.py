#!/usr/bin/env python3
"""Record testbench MAS-1 (orchestrator-workers) and print an OTel-style span tree.

Uses the local editable Chronicle + stub LLM (no API keys). LangGraph nodes are
instrumented as chain spans; each node's LLM call nests underneath (parent_span_id).

    PYTHONPATH=/Users/susheemkoul/Desktop/testbench/src \\
      python examples/otel_tree_mas1.py
"""

from __future__ import annotations

import sys
from functools import partial
from pathlib import Path

from langgraph.graph import END, StateGraph

import chronicle
from chronicle import JsonlStore

TESTBENCH_SRC = Path("/Users/susheemkoul/Desktop/testbench/src")
if str(TESTBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(TESTBENCH_SRC))

from testbench.core import NullSink, RunConfig  # noqa: E402
from testbench.core.llm import Message, ModelResponse, Usage  # noqa: E402
from testbench.core.stub import StubClient  # noqa: E402
from testbench.orchestrator_workers import workers  # noqa: E402
from testbench.orchestrator_workers.state import ResearchState  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "outputs" / "mas1_otel_tree"
TASK = "What is token governance and why does it matter for agents?"


def _wrap_stub(client: StubClient):
    """Chronicle-wrap StubClient.complete as an llm span."""

    def dispatch(model: str, messages: list[Message], **kwargs):
        return client.complete(model, messages, **kwargs)

    def extract_input(model, messages, **kwargs):
        from chronicle.envelope.schema import Input

        return Input(
            messages=[{"role": m.role, "content": m.content} for m in messages],
            arguments={"model": model},
        )

    def extract_result(resp: ModelResponse):
        return {
            "content": resp.text,
            "model": resp.model,
            "usage": {
                "prompt_tokens": resp.usage.input_tokens,
                "completion_tokens": resp.usage.output_tokens,
            },
        }

    def extract_metadata(resp):
        if isinstance(resp, dict):
            return {"model": resp.get("model")}
        return {"model": getattr(resp, "model", None)}

    return chronicle.wrap_llm(
        "llm",
        dispatch,
        extract_input=extract_input,
        extract_result=extract_result,
        extract_metadata=extract_metadata,
    )


class _InstrumentedClient:
    """LLMClient whose complete() is Chronicle-wrapped."""

    def __init__(self, complete):
        self.complete = complete


def build_instrumented_graph(client, sink, cfg):
    """Same MAS-1 wiring as testbench, with every node as a Chronicle boundary."""
    raw = {
        "supervisor": partial(workers.supervisor_node, client=client, sink=sink, cfg=cfg),
        "researcher": partial(workers.researcher_node, client=client, sink=sink, cfg=cfg),
        "analyst": partial(workers.analyst_node, client=client, sink=sink, cfg=cfg),
        "writer": partial(workers.writer_node, client=client, sink=sink, cfg=cfg),
    }
    nodes = chronicle.instrument_langgraph(raw, kind="custom")

    g = StateGraph(ResearchState)
    for name, fn in nodes.items():
        g.add_node(name, fn)
    g.set_entry_point("supervisor")
    g.add_conditional_edges(
        "supervisor",
        workers.route,
        {"researcher": "researcher", "analyst": "analyst", "writer": "writer", "FINISH": END},
    )
    for worker in ("researcher", "analyst", "writer"):
        g.add_edge(worker, "supervisor")
    return g.compile()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    store_path = OUT / "spans.jsonl"
    if store_path.exists():
        store_path.unlink()

    stub = StubClient()
    llm = _wrap_stub(stub)
    client = _InstrumentedClient(llm)
    sink = NullSink()
    cfg = RunConfig()

    attributes = {
        "session_id": "sess_mas1_demo",
        "message_id": "msg_001",
        "user_id": "dev",
        "workload": "mas1",
        "mode": "stub",
    }

    with chronicle.record(
        "mas1-otel-tree",
        store=JsonlStore(store_path),
        attributes=attributes,
        export=OUT / "trace",
    ) as session:
        graph = build_instrumented_graph(client, sink, cfg)
        result = graph.invoke(
            ResearchState(
                task=TASK, plan="", research="", analysis="", brief="", next=""
            )
        )

    graph = chronicle.ExecutionGraph.from_envelopes(session.trace_id, session.envelopes)
    tree = graph.to_otel_tree()
    tree_path = OUT / "otel_tree.txt"
    tree_path.write_text(tree + "\n", encoding="utf-8")

    print(tree)
    print()
    print(f"envelopes={len(session.envelopes)}  jsonl={store_path}")
    print(f"fixture={OUT / 'trace'}  tree={tree_path}")
    brief = (result or {}).get("brief") or ""
    if brief:
        print(f"brief={brief[:120]!r}")


if __name__ == "__main__":
    main()
