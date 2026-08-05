"""Input capture / _json_safe keep message metadata intact."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import chronicle
from chronicle import boundary
from chronicle.boundary import _json_safe
from chronicle.session import reset_session


@dataclass
class RichMessage:
    role: str
    content: str
    name: str | None = None
    tool_calls: list | None = None


def test_json_safe_dataclass_keeps_extra_message_fields():
    msg = RichMessage(
        role="assistant",
        content="ok",
        name="planner",
        tool_calls=[{"id": "1", "name": "search", "arguments": {}}],
    )
    out = _json_safe(msg)
    assert out["role"] == "assistant"
    assert out["content"] == "ok"
    assert out["name"] == "planner"
    assert out["tool_calls"][0]["name"] == "search"


def test_json_safe_duck_typed_message_keeps_public_attrs():
    msg = SimpleNamespace(
        role="assistant",
        content="done",
        tool_call_id="call_9",
        name="tool",
    )
    out = _json_safe(msg)
    assert out["tool_call_id"] == "call_9"
    assert out["name"] == "tool"


def test_bind_input_coerces_every_message_not_just_first():
    reset_session()

    @boundary("agent", kind="llm")
    def agent(messages):
        return {"completion": "ok", "finish_reason": "stop"}

    mixed = [
        {"role": "user", "content": "hi"},
        RichMessage(role="assistant", content="yo", name="bot", tool_calls=[]),
    ]
    with chronicle.record("t") as session:
        agent(mixed)

    recorded = session._recorded_envelopes[-1].input_state.messages
    assert recorded[0] == {"role": "user", "content": "hi"}
    assert recorded[1]["role"] == "assistant"
    assert recorded[1]["name"] == "bot"
    assert recorded[1]["tool_calls"] == []
