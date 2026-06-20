"""Unified boundary decorator for record and replay."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, TypeVar

from chronicle.envelope.schema import InputState
from chronicle.session import SessionMode, get_session, result_to_action_result

F = TypeVar("F", bound=Callable[..., Any])


def boundary(
    boundary_id: str,
    *,
    kind: str = "custom",
    extract_input: Callable[..., InputState] | None = None,
    extract_result: Callable[[Any], Any] | None = None,
) -> Callable[[F], F]:
    """
    Annotate a decision boundary for Chronicle record and replay.

    LIVE mode:     execute function, record envelope
    REPLAY + STUB: return fixture without executing
    REPLAY + LIVE: execute function (cut-point), capture input/result for assertions
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            session = get_session()

            if session.mode == SessionMode.LIVE:
                return _record_call(
                    session, fn, boundary_id, kind, args, kwargs,
                    extract_input, extract_result,
                )

            invocation_index = session._replay_cursor.get(boundary_id, 0) + 1
            if session.replay_plan.should_stub(boundary_id, invocation_index):
                return session.stub_result(boundary_id, kind)

            return _live_cutpoint_call(
                session, fn, boundary_id, kind, args, kwargs,
                extract_input, extract_result, invocation_index,
            )

        return wrapper  # type: ignore[return-value]

    return decorator


def _default_input_state(args: tuple, kwargs: dict) -> InputState:
    graph_state: dict[str, Any] = {}
    if args and isinstance(args[0], dict):
        graph_state = dict(args[0])
    elif kwargs:
        graph_state = dict(kwargs)
    else:
        graph_state = {"args": list(args), "kwargs": kwargs}

    messages = graph_state.get("messages", [])
    if not messages and "user_message" in graph_state:
        messages = [{"role": "user", "content": graph_state["user_message"]}]

    return InputState(
        messages=messages,
        system_prompt=graph_state.get("system_prompt"),
        graph_state=graph_state,
    )


def _record_call(session, fn, boundary_id, kind, args, kwargs, extract_input, extract_result):
    input_state = (
        extract_input(*args, **kwargs)
        if extract_input
        else _default_input_state(args, kwargs)
    )
    result = fn(*args, **kwargs)
    if extract_result:
        result = extract_result(result)
    action_result = result_to_action_result(result, kind)
    session.record_envelope(boundary_id, kind, input_state, action_result)
    return result


def _live_cutpoint_call(
    session, fn, boundary_id, kind, args, kwargs,
    extract_input, extract_result, invocation_index,
):
    input_state = (
        extract_input(*args, **kwargs)
        if extract_input
        else _default_input_state(args, kwargs)
    )
    session.capture_live_input(boundary_id, invocation_index, input_state)
    result = fn(*args, **kwargs)
    if extract_result:
        result = extract_result(result)
    session.capture_live_result(boundary_id, invocation_index, result)
    session.next_invocation(boundary_id)
    session._replay_cursor[boundary_id] = invocation_index
    return result
