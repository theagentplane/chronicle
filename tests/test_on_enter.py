"""Tests for ChronicleSession.on_enter / on_leave pre-call hooks."""

from __future__ import annotations

import pytest

from chronicle.boundary import boundary
from chronicle.session import reset_session


@boundary("chat", kind="llm")
def chat(model: str, messages: list, *, max_output_tokens: int | None = None) -> dict:
    return {
        "content": "ok",
        "model": model,
        "max_output_tokens": max_output_tokens,
        "n_messages": len(messages),
    }


@pytest.mark.layer1
def test_on_enter_runs_before_function():
    order: list[str] = []

    @boundary("step", kind="llm")
    def step(x: int) -> int:
        order.append("fn")
        return x

    session = reset_session()
    session.enable_live()

    def on_enter(boundary_id, kind, input_state):
        order.append(f"enter:{boundary_id}:{kind}")
        return None

    session.on_enter = on_enter
    assert step(1) == 1
    assert order == ["enter:step:llm", "fn"]


@pytest.mark.layer1
def test_on_enter_can_patch_kwargs():
    session = reset_session()
    session.enable_live()
    session.on_enter = lambda *_: {"max_output_tokens": 128}

    out = chat("gpt-4o-mini", [{"role": "user", "content": "hi"}])
    assert out["max_output_tokens"] == 128


@pytest.mark.layer1
def test_on_enter_raise_skips_function_and_on_leave():
    called = {"fn": False, "leave": False}

    @boundary("blocked", kind="llm")
    def blocked() -> str:
        called["fn"] = True
        return "nope"

    session = reset_session()
    session.enable_live()

    class PreCallAbort(BaseException):
        pass

    def on_enter(*_):
        raise PreCallAbort("halt")

    def on_leave(*_):
        called["leave"] = True

    session.on_enter = on_enter
    session.on_leave = on_leave

    with pytest.raises(PreCallAbort):
        blocked()
    assert called == {"fn": False, "leave": False}


@pytest.mark.layer1
def test_on_leave_pairs_with_successful_on_enter():
    events: list[str] = []

    @boundary("t", kind="tool")
    def tool(x: int) -> int:
        events.append("fn")
        return x

    session = reset_session()
    session.enable_live()
    session.on_enter = lambda *_: (events.append("enter") or None)
    session.on_leave = lambda *_: events.append("leave")

    assert tool(3) == 3
    assert events == ["enter", "fn", "leave"]


@pytest.mark.layer1
def test_on_leave_runs_when_function_raises():
    events: list[str] = []

    @boundary("t", kind="tool")
    def boom() -> None:
        events.append("fn")
        raise ValueError("x")

    session = reset_session()
    session.enable_live()
    session.on_enter = lambda *_: (events.append("enter") or None)
    session.on_leave = lambda *_: events.append("leave")

    with pytest.raises(ValueError):
        boom()
    assert events == ["enter", "fn", "leave"]
