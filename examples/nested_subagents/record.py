#!/usr/bin/env python3
"""Record an orchestrator that calls the same sub-agent twice (no API keys needed).

Each ``researcher`` run nests an ``llm`` call and a ``web_search`` tool call under it,
so the trace has real parent/child spans. Writes the trace fixture plus its OTel-style
tree and waterfall renderings.

    python examples/nested_subagents/record.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import chronicle  # noqa: E402
from chronicle import boundary  # noqa: E402

OUT = ROOT / "fixtures" / "traces" / "parent-calls-subagent-twice"


@boundary("llm", kind="llm")
def llm(messages: list[dict]) -> dict:
    time.sleep(0.01)
    return {
        "completion": f"Plan: search for '{messages[-1]['content']}'",
        "model": "stub-researcher",
        "finish_reason": "stop",
    }


@boundary("web_search", kind="tool")
def web_search(query: str) -> dict:
    time.sleep(0.01)
    return {"query": query, "results": [f"result for {query}"]}


@boundary("researcher")
def researcher(topic: str) -> dict:
    plan = llm([{"role": "user", "content": topic}])
    found = web_search(topic)
    return {"topic": topic, "plan": plan["completion"], "results": found["results"]}


@boundary("orchestrator")
def orchestrator(task: str) -> dict:
    return {
        "task": task,
        "findings": [researcher("token governance"), researcher("agent cost controls")],
    }


def main() -> None:
    with chronicle.record(
        "parent-calls-subagent-twice",
        export=OUT,
        dims={
            "session_id": "sess_subagent_x2",
            "message_id": "msg_042",
            "user_id": "dev",
            "scenario": "parent_calls_subagent_twice",
        },
    ) as session:
        orchestrator("Summarize token governance and agent cost controls")

    graph = chronicle.ExecutionGraph.from_envelopes(session.trace_id, session.envelopes)
    (OUT / "otel_tree.txt").write_text(graph.to_otel_tree() + "\n", encoding="utf-8")
    (OUT / "otel_waterfall.txt").write_text(graph.to_otel_waterfall() + "\n", encoding="utf-8")
    print(graph.to_otel_tree())
    print(f"\nexported to {OUT}")


if __name__ == "__main__":
    main()
