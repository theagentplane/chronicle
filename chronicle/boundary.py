"""Unified boundary decorator for record and replay."""

from __future__ import annotations

import functools
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from chronicle.envelope.schema import InputState
from chronicle.session import (
    SessionMode,
    get_session,
    model_version_from,
    result_to_action_result,
    sampling_params_from,
)

F = TypeVar("F", bound=Callable[..., Any])


def boundary(
    boundary_id: str,
    *,
    kind: str = "custom",
    extract_input: Callable[..., InputState] | None = None,
    extract_result: Callable[[Any], Any] | None = None,
    extract_metadata: Callable[[Any], Mapping[str, Any]] | None = None,
) -> Callable[[F], F]:
    """
    Annotate a decision boundary for Chronicle record and replay.

    LIVE mode:     execute function, record envelope
    REPLAY + STUB: return fixture without executing
    REPLAY + LIVE: execute function (cut-point), capture input/result for assertions

    extract_metadata lets a boundary surface the real model version and sampling
    parameters it used (returned as a mapping) so the envelope pins what actually
    ran. For ``kind="llm"`` these are also auto-detected from conventional keys on
    the returned dict (``model``/``model_version``, ``temperature``, ``top_p``,
    ``max_tokens``, ``seed``); the hook, when given, takes precedence.
    """

    def decorator(fn: F) -> F:
        return _bind_boundary(  # type: ignore[return-value]
            fn,
            boundary_id,
            kind,
            extract_input=extract_input,
            extract_result=extract_result,
            extract_metadata=extract_metadata,
        )

    return decorator


def wrap_llm(
    boundary_id: str,
    dispatch: Callable[..., Any],
    *,
    extract_input: Callable[..., InputState] | None = None,
    extract_result: Callable[[Any], Any] | None = None,
    extract_metadata: Callable[[Any], Mapping[str, Any]] | None = None,
) -> Callable[..., Any]:
    """Wrap an LLM callable with Chronicle tracing (``kind="llm"``).

    Chronicle owns the tracer; governors subscribe via ``session.on_crossing``.
    Same LIVE / stub-replay / live cut-point contract as
    ``@boundary(..., kind="llm")``: execute + record envelope, then fire
    ``on_crossing(boundary_id, kind, input_state, result)``.

    Prefer this when the LLM entry point is a dispatch function rather than a
    named method you can decorate (e.g. TokenOps ``wrap_complete`` bridging).

    Common dispatch shapes (default ``extract_input`` handles these):

    - ``(messages) -> result`` / ``(messages, **kwargs) -> result``
    - ``(provider, model, messages, **kwargs) -> result``
    - graph-state ``({"messages": ...},) -> result`` (same as ``@boundary``)

    Pass ``extract_input`` / ``extract_result`` / ``extract_metadata`` when the
    callable does not match those shapes.
    """
    return _bind_boundary(
        dispatch,
        boundary_id,
        "llm",
        extract_input=extract_input if extract_input is not None else _llm_default_input,
        extract_result=extract_result,
        extract_metadata=extract_metadata,
    )


def _bind_boundary(
    fn: Callable[..., Any],
    boundary_id: str,
    kind: str,
    *,
    extract_input: Callable[..., InputState] | None,
    extract_result: Callable[[Any], Any] | None,
    extract_metadata: Callable[[Any], Mapping[str, Any]] | None,
) -> Callable[..., Any]:
    """Shared LIVE / replay wrapper used by ``@boundary`` and ``wrap_llm``."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        session = get_session()

        if session.mode == SessionMode.LIVE:
            return _record_call(
                session, fn, boundary_id, kind, args, kwargs,
                extract_input, extract_result, extract_metadata,
            )

        invocation_index = session._replay_cursor.get(boundary_id, 0) + 1
        if session.replay_plan.should_stub(boundary_id, invocation_index):
            return session.stub_result(boundary_id, kind)

        return _live_cutpoint_call(
            session, fn, boundary_id, kind, args, kwargs,
            extract_input, extract_result, invocation_index,
        )

    return wrapper


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


def _llm_default_input(*args: Any, **kwargs: Any) -> InputState:
    """Best-effort ``InputState`` for common LLM dispatch signatures."""
    if "messages" in kwargs:
        messages = list(kwargs["messages"])
        graph_state = dict(kwargs)
        graph_state["messages"] = messages
        return InputState(
            messages=messages,
            system_prompt=graph_state.get("system_prompt"),
            graph_state=graph_state,
        )

    if args and isinstance(args[0], dict):
        return _default_input_state(args, kwargs)

    if len(args) >= 3 and isinstance(args[2], (list, tuple)):
        # (provider, model, messages, **kwargs)
        messages = list(args[2])
        graph_state: dict[str, Any] = {
            "provider": args[0],
            "model": args[1],
            "messages": messages,
            **kwargs,
        }
        return InputState(
            messages=messages,
            system_prompt=graph_state.get("system_prompt"),
            graph_state=graph_state,
        )

    if args and isinstance(args[0], (list, tuple)):
        # (messages) or (messages, **kwargs)
        messages = list(args[0])
        graph_state = {"messages": messages, **kwargs}
        return InputState(
            messages=messages,
            system_prompt=graph_state.get("system_prompt"),
            graph_state=graph_state,
        )

    return _default_input_state(args, kwargs)


def _record_call(session, fn, boundary_id, kind, args, kwargs, extract_input, extract_result, extract_metadata):
    input_state = (
        extract_input(*args, **kwargs)
        if extract_input
        else _default_input_state(args, kwargs)
    )
    result = fn(*args, **kwargs)
    if extract_result:
        result = extract_result(result)
    action_result = result_to_action_result(result, kind)
    model_version, sampling_params = _call_metadata(result, kind, extract_metadata)
    session.record_envelope(
        boundary_id, kind, input_state, action_result,
        model_version=model_version, sampling_params=sampling_params,
    )
    if session.on_crossing is not None:
        session.on_crossing(boundary_id, kind, input_state, result)
    return result


def _call_metadata(result, kind, extract_metadata):
    """Capture the real model version and sampling params for this crossing.

    Model metadata only applies to ``llm`` boundaries, so tool and router
    results are not scraped for a stray ``model`` key. An explicit
    extract_metadata hook always wins and works for any kind. Returns
    ``(None, None)`` when nothing is available, letting record_envelope fall
    back to the session default.
    """
    if extract_metadata is not None:
        source = extract_metadata(result)
        return model_version_from(source), sampling_params_from(source)
    if kind == "llm":
        return model_version_from(result), sampling_params_from(result)
    return None, None


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
    if session.on_crossing is not None:
        session.on_crossing(boundary_id, kind, input_state, result)
    return result
