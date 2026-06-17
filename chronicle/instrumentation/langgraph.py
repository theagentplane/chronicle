"""LangGraph node instrumentation helpers."""

from __future__ import annotations

from typing import Any

from chronicle.envelope.capture import EnvelopeRecorder
from chronicle.envelope.schema import ActionResult, InputState, RagChunk, ToolCall


def langgraph_input_extractor(state: dict[str, Any]) -> InputState:
    """Extract canonical InputState from a LangGraph state dict."""
    messages = state.get("messages", [])
    serialized_messages: list[dict[str, Any]] = []
    for msg in messages:
        if hasattr(msg, "model_dump"):
            serialized_messages.append(msg.model_dump())
        elif hasattr(msg, "dict"):
            serialized_messages.append(msg.dict())
        elif isinstance(msg, dict):
            serialized_messages.append(msg)
        else:
            serialized_messages.append({"role": "unknown", "content": str(msg)})

    rag_chunks = []
    for chunk in state.get("rag_chunks", state.get("context", [])):
        if isinstance(chunk, RagChunk):
            rag_chunks.append(chunk)
        elif isinstance(chunk, dict):
            rag_chunks.append(RagChunk(**chunk))
        elif isinstance(chunk, str):
            rag_chunks.append(RagChunk(chunk_id=str(len(rag_chunks)), content=chunk))

    return InputState(
        messages=serialized_messages,
        system_prompt=state.get("system_prompt"),
        rag_chunks=rag_chunks,
        graph_state={k: v for k, v in state.items() if k != "messages"},
    )


def langgraph_result_extractor(state: dict[str, Any], result: Any) -> ActionResult:
    """Extract ActionResult from LangGraph node return value."""
    if isinstance(result, dict):
        tool_calls = []
        for tc in result.get("tool_calls", []):
            if isinstance(tc, ToolCall):
                tool_calls.append(tc)
            elif isinstance(tc, dict):
                tool_calls.append(
                    ToolCall(
                        id=tc.get("id"),
                        name=tc.get("name", ""),
                        arguments=tc.get("arguments", tc.get("args", {})),
                    )
                )

        completion = result.get("completion") or result.get("output")
        if completion is None and "messages" in result:
            msgs = result["messages"]
            if msgs:
                last = msgs[-1]
                if hasattr(last, "content"):
                    completion = last.content
                elif isinstance(last, dict):
                    completion = last.get("content")

        return ActionResult(
            tool_calls=tool_calls,
            completion=str(completion) if completion is not None else None,
            finish_reason=result.get("finish_reason"),
            token_usage=result.get("token_usage", {}),
        )

    if isinstance(result, str):
        return ActionResult(completion=result)

    return ActionResult(completion=str(result))


def instrument_graph_nodes(
    recorder: EnvelopeRecorder,
    nodes: dict[str, Any],
) -> dict[str, Any]:
    """
    Wrap all nodes in a LangGraph node dict with envelope recording.

    Usage:
        graph = StateGraph(MyState)
        nodes = {"agent": agent_node, "tools": tool_node}
        instrumented = instrument_graph_nodes(recorder, nodes)
        for name, fn in instrumented.items():
            graph.add_node(name, fn)
    """
    instrumented: dict[str, Any] = {}
    for node_id, fn in nodes.items():
        instrumented[node_id] = recorder.wrap_node(
            node_id,
            extract_input=langgraph_input_extractor,
            extract_result=langgraph_result_extractor,
        )(fn)
    return instrumented
