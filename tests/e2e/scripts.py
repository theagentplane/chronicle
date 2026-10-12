"""Scripted LLM replies for an agent, per wire format."""

from typing import Any

from tests.e2e.agents.factory import ANTHROPIC_WIRE
from tests.support.fake_llm_server import (
    Scripted,
    anthropic_text,
    anthropic_tool_use,
    openai_text,
    openai_tool_call,
)


def final(framework: str, text: str, **kwargs: Any) -> Scripted:
    """A plain text reply on the framework's wire format."""
    if framework in ANTHROPIC_WIRE:
        return anthropic_text(text, **kwargs)
    return openai_text(text, **kwargs)


def call_tool(framework: str, tool: str, arguments: dict[str, Any]) -> Scripted:
    """A reply asking for one tool call."""
    if framework in ANTHROPIC_WIRE:
        return anthropic_tool_use(tool, arguments)
    return openai_tool_call(tool, arguments)


def call_tools(framework: str, calls: list[tuple[str, dict[str, Any]]]) -> Scripted:
    """A reply asking for several tool calls in one message (parallel fan-out)."""
    if framework in ANTHROPIC_WIRE:
        body = anthropic_text("")
        body["content"] = [
            {"type": "tool_use", "id": f"toolu_{i}", "name": name, "input": args}
            for i, (name, args) in enumerate(calls)
        ]
        body["stop_reason"] = "tool_use"
        return body
    body = openai_text("")
    message = body["choices"][0]["message"]
    message["content"] = None
    import json

    message["tool_calls"] = [
        {
            "id": f"call_{i}",
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)},
        }
        for i, (name, args) in enumerate(calls)
    ]
    body["choices"][0]["finish_reason"] = "tool_calls"
    return body


def delegate_then_answer(framework: str, tool: str, task: str, answer: str) -> list[Scripted]:
    """Ask a peer through ``tool``, then answer."""
    return [call_tool(framework, tool, {"task": task}), final(framework, answer)]
