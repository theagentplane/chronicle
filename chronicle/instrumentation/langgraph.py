"""LangGraph node instrumentation helpers."""

from __future__ import annotations

from typing import Any

from chronicle.envelope.capture import EnvelopeRecorder
from chronicle.envelope.schema import Input, LLMOutput, Message, Output, ToolCall
from chronicle.session import usage_from


def langgraph_input_extractor(state: dict[str, Any]) -> Input:
    """Extract canonical Input from a LangGraph state dict."""
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

    return Input(
        arguments={k: v for k, v in state.items() if k != "messages"},
        messages=[
            Message(**m) if "role" in m else Message(role="unknown", content=m)
            for m in serialized_messages
        ],
    )


def langgraph_result_extractor(state: dict[str, Any], result: Any) -> Output:
    """Extract Output from LangGraph node return value."""
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

        return Output(
            llm=LLMOutput(
                text=str(completion) if completion is not None else None,
                tool_calls=tool_calls,
                finish_reason=result.get("finish_reason"),
                usage=usage_from(result.get("token_usage") or result.get("usage")),
            )
        )

    if isinstance(result, str):
        return Output(llm=LLMOutput(text=result))

    return Output(value=str(result))


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
