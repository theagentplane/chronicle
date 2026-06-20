"""
Minimal LangGraph demo with Chronicle envelope recording.

Run:
    pip install -e ".[dev]"
    python examples/langgraph_demo/agent.py
"""

from __future__ import annotations

import os
from typing import Annotated, TypedDict

from chronicle.envelope.capture import EnvelopeRecorder
from chronicle.envelope.schema import ActionResult, RagChunk, SamplingParams, ToolSchema
from chronicle.envelope.store import EnvelopeStore
from chronicle.instrumentation.langgraph import (
    langgraph_input_extractor,
    langgraph_result_extractor,
)

try:
    from langgraph.graph import END, StateGraph
except ImportError:
    print("Install langgraph: pip install chronicle[langgraph]")
    raise


class AgentState(TypedDict):
    messages: list[dict]
    system_prompt: str
    rag_chunks: list[dict]
    step: str
    completion: str
    tool_calls: list[dict]
    finish_reason: str


def retrieve_node(state: AgentState) -> AgentState:
    return {
        **state,
        "rag_chunks": [
            RagChunk(
                chunk_id="doc-42",
                content="API keys can be reset from Settings > API Keys > Regenerate.",
                source="docs/api-keys.md",
                index_version="v3.2.1",
            ).model_dump()
        ],
        "step": "retrieve",
    }


def agent_node(state: AgentState) -> AgentState:
    return {
        **state,
        "tool_calls": [{"id": "call_1", "name": "search_docs", "arguments": {"query": "reset API key"}}],
        "completion": "You can reset your API key from Settings > API Keys > Regenerate.",
        "finish_reason": "tool_calls",
        "step": "agent",
    }


def build_graph(recorder: EnvelopeRecorder):
    graph = StateGraph(AgentState)

    wrapped_retrieve = recorder.wrap_node(
        "retrieve",
        extract_input=langgraph_input_extractor,
        extract_result=langgraph_result_extractor,
    )(retrieve_node)

    wrapped_agent = recorder.wrap_node(
        "agent",
        extract_input=langgraph_input_extractor,
        extract_result=langgraph_result_extractor,
    )(agent_node)

    graph.add_node("retrieve", wrapped_retrieve)
    graph.add_node("agent", wrapped_agent)
    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "agent")
    graph.add_edge("agent", END)
    return graph.compile()


def main() -> None:
    store_path = os.environ.get("CHRONICLE_STORE", ".chronicle/runs/demo.jsonl")
    store = EnvelopeStore(store_path)

    recorder = EnvelopeRecorder(
        store=store,
        model_version="gpt-4o-2024-08-06",
        build_id=os.environ.get("CHRONICLE_BUILD_ID", "demo-local"),
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
    print(f"Recorded {len(envelopes)} envelope(s) to {store_path}")
    for e in envelopes:
        print(f"  node={e.node_id}  tools={[tc.name for tc in e.action_result.tool_calls]}")
    print(f"Completion: {result['completion']}")


if __name__ == "__main__":
    main()
