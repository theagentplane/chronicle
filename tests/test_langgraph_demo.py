"""examples/langgraph_demo/agent.py: node crossings get recorded as Envelopes."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

pytest.importorskip("langgraph")

from chronicle.envelope.capture import EnvelopeRecorder
from chronicle.envelope.schema import SamplingParams, ToolSchema
from chronicle.envelope.store import EnvelopeStore
from examples.langgraph_demo.agent import build_graph


@pytest.mark.layer1
def test_langgraph_demo_records_both_nodes(tmp_path):
    store = EnvelopeStore(tmp_path / "demo.jsonl")
    recorder = EnvelopeRecorder(
        store=store,
        model_version="gpt-4o-2024-08-06",
        build_id="test",
        sampling_params=SamplingParams(temperature=0.0, seed=42),
        tool_schemas=[
            ToolSchema(
                name="search_docs",
                description="Search internal documentation",
                parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            )
        ],
        framework="langgraph",
    )

    app = build_graph(recorder)
    result = app.invoke(
        {
            "messages": [{"role": "user", "content": "How do I reset my API key?"}],
            "system_prompt": "You are a helpful support agent.",
            "rag_chunks": [],
            "step": "start",
            "completion": "",
            "tool_calls": [],
            "finish_reason": "",
        }
    )

    envelopes = store.read_all()
    assert [e.node_id for e in envelopes] == ["retrieve", "agent"]
    assert envelopes[1].action_result.tool_calls[0].name == "search_docs"
    assert result["completion"] == "You can reset your API key from Settings > API Keys > Regenerate."
