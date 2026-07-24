"""Unified boundary decorator for record and replay.

Design rules this module holds to:

- **Transparency is sacred.** The wrapper never changes what the function
  returns, raises, or how it is called. Extractors feed the *envelope* only; the
  caller always gets the real value, and exceptions propagate unchanged (a failed
  crossing is recorded, then re-raised).
- **Zero-config is correct, not clever.** A bare ``@boundary`` binds the real
  signature and records arguments by their real names. No shape-sniffing, so what
  you capture never depends on how you happened to call the function.

Both sync functions and ``async def`` coroutines are supported. Async generators
(streaming) are a planned follow-up.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from chronicle.envelope.schema import ActionResult, InputState
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

    LIVE mode:     execute the function, record an envelope, return its real value
    REPLAY + STUB: return the recorded fixture without executing
    REPLAY + LIVE: execute the function (cut-point), capture input/result for asserts

    Works on sync functions and ``async def`` coroutines. The wrapper is
    transparent: the caller always gets exactly what the function returned (or the
    exception it raised, after the failure is recorded).

    The optional hooks feed the *envelope* only, never the return value:
    - ``extract_input(*args, **kwargs) -> InputState`` overrides the default
      signature-bound capture.
    - ``extract_result(result) -> value`` shapes what is recorded (the caller
      still receives the original ``result``).
    - ``extract_metadata(result) -> mapping`` surfaces the real model version and
      sampling params. For ``kind="llm"`` these are also auto-detected from
      conventional keys on the returned dict; the hook wins when given.
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
    Same transparent LIVE / stub-replay / live cut-point contract as
    ``@boundary(..., kind="llm")``. Prefer this when the LLM entry point is a
    dispatch function rather than a named method you can decorate (e.g. TokenOps
    ``wrap_complete`` bridging).

    The default capture binds the dispatch signature, so common shapes such as
    ``(messages, **kwargs)`` or ``(provider, model, messages, **kwargs)`` are
    recorded by name with no extractor. Pass ``extract_input`` when the callable's
    signature cannot be introspected (some builtins/C callables).
    """
    return _bind_boundary(
        dispatch,
        boundary_id,
        "llm",
        extract_input=extract_input,
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
    """Shared LIVE / replay wrapper for ``@boundary`` and ``wrap_llm`` (sync + async)."""

    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            session = get_session()
            if session.mode == SessionMode.LIVE:
                return await _record_call_async(
                    session, fn, boundary_id, kind, args, kwargs,
                    extract_input, extract_result, extract_metadata,
                )
            invocation_index = session._replay_cursor.get(boundary_id, 0) + 1
            if session.replay_plan.should_stub(boundary_id, invocation_index):
                return session.stub_result(boundary_id, kind)
            return await _live_cutpoint_call_async(
                session, fn, boundary_id, kind, args, kwargs,
                extract_input, invocation_index,
            )

        return async_wrapper

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
            extract_input, invocation_index,
        )

    return wrapper


# --------------------------------------------------------------------------- #
# Recording (LIVE mode)
# --------------------------------------------------------------------------- #

def _record_call(session, fn, boundary_id, kind, args, kwargs, extract_input, extract_result, extract_metadata):
    input_state = _capture_input(fn, args, kwargs, extract_input)
    try:
        result = fn(*args, **kwargs)
    except Exception as exc:
        _record_failure(session, boundary_id, kind, input_state, exc)
        raise
    _record_success(session, boundary_id, kind, input_state, result, extract_result, extract_metadata)
    return result


async def _record_call_async(session, fn, boundary_id, kind, args, kwargs, extract_input, extract_result, extract_metadata):
    input_state = _capture_input(fn, args, kwargs, extract_input)
    try:
        result = await fn(*args, **kwargs)
    except Exception as exc:
        _record_failure(session, boundary_id, kind, input_state, exc)
        raise
    _record_success(session, boundary_id, kind, input_state, result, extract_result, extract_metadata)
    return result


def _record_success(session, boundary_id, kind, input_state, result, extract_result, extract_metadata):
    """Record the envelope, then notify observers. Never touches the return value."""
    recorded = extract_result(result) if extract_result else result
    action_result = result_to_action_result(recorded, kind)
    model_version, sampling_params = _call_metadata(recorded, kind, extract_metadata)
    session.record_envelope(
        boundary_id, kind, input_state, action_result,
        model_version=model_version, sampling_params=sampling_params,
    )
    if session.on_crossing is not None:
        session.on_crossing(boundary_id, kind, input_state, result)


def _record_failure(session, boundary_id, kind, input_state, exc):
    """Record a failed crossing so incidents that raise are still reproducible."""
    action_result = ActionResult(
        error=str(exc),
        error_type=type(exc).__name__,
        finish_reason="error",
    )
    session.record_envelope(boundary_id, kind, input_state, action_result)


def _call_metadata(result, kind, extract_metadata):
    """Capture the real model version and sampling params for this crossing.

    Model metadata only applies to ``llm`` boundaries, so tool and router results
    are not scraped for a stray ``model`` key. An explicit extract_metadata hook
    always wins and works for any kind. Returns ``(None, None)`` when nothing is
    available, letting record_envelope fall back to the session default.
    """
    if extract_metadata is not None:
        source = extract_metadata(result)
        return model_version_from(source), sampling_params_from(source)
    if kind == "llm":
        return model_version_from(result), sampling_params_from(result)
    return None, None


# --------------------------------------------------------------------------- #
# Cut-point (REPLAY mode, live boundary). No envelope; capture for assertions.
# --------------------------------------------------------------------------- #

def _live_cutpoint_call(session, fn, boundary_id, kind, args, kwargs, extract_input, invocation_index):
    input_state = _capture_input(fn, args, kwargs, extract_input)
    session.capture_live_input(boundary_id, invocation_index, input_state)
    try:
        result = fn(*args, **kwargs)
    except Exception:
        _advance_cutpoint(session, boundary_id, invocation_index)
        raise
    _finish_cutpoint(session, boundary_id, kind, input_state, result, invocation_index)
    return result


async def _live_cutpoint_call_async(session, fn, boundary_id, kind, args, kwargs, extract_input, invocation_index):
    input_state = _capture_input(fn, args, kwargs, extract_input)
    session.capture_live_input(boundary_id, invocation_index, input_state)
    try:
        result = await fn(*args, **kwargs)
    except Exception:
        _advance_cutpoint(session, boundary_id, invocation_index)
        raise
    _finish_cutpoint(session, boundary_id, kind, input_state, result, invocation_index)
    return result


def _finish_cutpoint(session, boundary_id, kind, input_state, result, invocation_index):
    session.capture_live_result(boundary_id, invocation_index, result)
    _advance_cutpoint(session, boundary_id, invocation_index)
    if session.on_crossing is not None:
        session.on_crossing(boundary_id, kind, input_state, result)


def _advance_cutpoint(session, boundary_id, invocation_index):
    session.next_invocation(boundary_id)
    session._replay_cursor[boundary_id] = invocation_index


# --------------------------------------------------------------------------- #
# Zero-config input capture: bind the real signature, record args by name.
# --------------------------------------------------------------------------- #

_IO_KEYS = ("messages", "system_prompt", "rag_chunks")


def _capture_input(fn, args, kwargs, extract_input) -> InputState:
    if extract_input is not None:
        return extract_input(*args, **kwargs)
    # The default capture must never break the wrapped call.
    try:
        return _bind_input_state(fn, args, kwargs)
    except Exception:
        return InputState(messages=[], graph_state={"args": _json_safe(list(args)), "kwargs": _json_safe(dict(kwargs))})


def _bind_input_state(fn, args, kwargs) -> InputState:
    graph_state = _bound_arguments(fn, args, kwargs)
    source = _io_source(graph_state)
    messages = source.get("messages") or []
    if not messages and "user_message" in source:
        messages = [{"role": "user", "content": source["user_message"]}]
    return InputState(
        messages=messages,
        system_prompt=source.get("system_prompt"),
        rag_chunks=_coerce_rag_chunks(source.get("rag_chunks")),
        graph_state=graph_state,
    )


def _bound_arguments(fn, args, kwargs) -> dict[str, Any]:
    """Record the call by real parameter names. Skip self/cls, flatten **kwargs.

    Falls back to positional capture when the callable has no introspectable
    signature (some builtins / C callables).
    """
    try:
        sig = inspect.signature(fn)
        bound = sig.bind_partial(*args, **kwargs)
    except (TypeError, ValueError):
        return {"args": _json_safe(list(args)), "kwargs": _json_safe(dict(kwargs))}

    graph_state: dict[str, Any] = {}
    for name, value in bound.arguments.items():
        if name in ("self", "cls"):
            continue
        param = sig.parameters.get(name)
        if param is not None and param.kind is inspect.Parameter.VAR_KEYWORD:
            for key, val in value.items():
                graph_state[str(key)] = _json_safe(val)
        elif param is not None and param.kind is inspect.Parameter.VAR_POSITIONAL:
            graph_state[name] = _json_safe(list(value))
        else:
            graph_state[name] = _json_safe(value)
    return graph_state


def _io_source(graph_state: dict[str, Any]) -> Mapping[str, Any]:
    """Where messages/system_prompt/rag_chunks live.

    Prefer top-level params of those names. Otherwise, if exactly one argument is a
    mapping that carries them (the graph-state convention, e.g. LangGraph
    ``node(state)``), read from inside it.
    """
    if any(k in graph_state for k in _IO_KEYS):
        return graph_state
    mappings = [v for v in graph_state.values() if isinstance(v, Mapping)]
    if len(mappings) == 1 and any(k in mappings[0] for k in (*_IO_KEYS, "user_message")):
        return mappings[0]
    return graph_state


def _coerce_rag_chunks(value: Any) -> list[Any]:
    """Only pass through items that look like RagChunk (have chunk_id + content)."""
    if (
        isinstance(value, (list, tuple))
        and value
        and all(isinstance(c, Mapping) and "chunk_id" in c and "content" in c for c in value)
    ):
        return list(value)
    return []


def _json_safe(value: Any, _depth: int = 0) -> Any:
    """Coerce captured args into a JSON-serializable form so recording never breaks
    the call. Data stays data; opaque objects (clients, connections) become repr."""
    if _depth > 6:
        return repr(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v, _depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v, _depth + 1) for v in value]
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump()
        except Exception:
            return repr(value)
    return repr(value)
