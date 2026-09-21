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

import dataclasses
import functools
import inspect
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from chronicle.config import is_enabled
from chronicle.envelope.genai import (
    LLMRequest,
    SamplingParams,
    infer_method_schema,
    model_from,
    sampling_params_from,
)
from chronicle.envelope.schema import Input, Message, Output, Status
from chronicle.session import (
    SessionMode,
    get_session,
    peek_session,
    result_to_output,
)

F = TypeVar("F", bound=Callable[..., Any])


def boundary(
    name: str,
    *,
    kind: str = "custom",
    extract_input: Callable[..., Input] | None = None,
    extract_result: Callable[[Any], Any] | None = None,
    extract_metadata: Callable[[Any], Mapping[str, Any]] | None = None,
) -> Callable[[F], F]:
    """
    Annotate a decision boundary for Chronicle record and replay.

    LIVE mode:     optional ``session.on_enter`` (may abort / patch kwargs), execute
                   the function, record an envelope, ``on_crossing``, then ``on_leave``
    REPLAY + STUB: return the recorded fixture without executing
    REPLAY + LIVE: execute the function (cut-point), capture input/result for asserts
                   (``on_enter`` / ``on_leave`` / ``on_crossing`` still apply)

    Works on sync functions and ``async def`` coroutines. The wrapper is
    transparent: the caller always gets exactly what the function returned (or the
    exception it raised, after the failure is recorded).

    The optional hooks feed the *envelope* only, never the return value:
    - ``extract_input(*args, **kwargs) -> Input`` overrides the default
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
            name,
            kind,
            extract_input=extract_input,
            extract_result=extract_result,
            extract_metadata=extract_metadata,
        )

    return decorator


def wrap_llm(
    name: str,
    dispatch: Callable[..., Any],
    *,
    extract_input: Callable[..., Input] | None = None,
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
        name,
        "llm",
        extract_input=extract_input,
        extract_result=extract_result,
        extract_metadata=extract_metadata,
    )


def _bind_boundary(
    fn: Callable[..., Any],
    name: str,
    kind: str,
    *,
    extract_input: Callable[..., Input] | None,
    extract_result: Callable[[Any], Any] | None,
    extract_metadata: Callable[[Any], Mapping[str, Any]] | None,
) -> Callable[..., Any]:
    """Shared LIVE / replay wrapper for ``@boundary`` and ``wrap_llm`` (sync + async)."""

    # Resolve once — inspect.signature dominates per-crossing cost otherwise.
    try:
        cached_sig: inspect.Signature | None = inspect.signature(fn)
    except (TypeError, ValueError):
        cached_sig = None
    # A method boundary's schema is inferred once from the wrapped method (signature,
    # return annotation, docstring). An LLM boundary has no method shape to infer.
    static_attributes = (
        None
        if kind == "llm"
        else infer_method_schema(fn, name).to_attributes()
    )

    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            if not is_enabled():
                # Passthrough for LIVE; still honor an active REPLAY session.
                session = peek_session()
                if session is None or session.mode == SessionMode.LIVE:
                    return await fn(*args, **kwargs)
            else:
                session = get_session()
            if session.mode == SessionMode.LIVE:
                return await _record_call_async(
                    session, fn, name, kind, args, kwargs,
                    extract_input, extract_result, extract_metadata, cached_sig, static_attributes,
                )
            invocation_index = session._replay_cursor.get(name, 0) + 1
            if session.replay_plan.should_stub(name, invocation_index):
                return session.stub_result(name, kind)
            return await _live_cutpoint_call_async(
                session, fn, name, kind, args, kwargs,
                extract_input, invocation_index, cached_sig,
            )

        return async_wrapper

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not is_enabled():
            # Passthrough for LIVE; still honor an active REPLAY session.
            session = peek_session()
            if session is None or session.mode == SessionMode.LIVE:
                return fn(*args, **kwargs)
        else:
            session = get_session()
        if session.mode == SessionMode.LIVE:
            return _record_call(
                session, fn, name, kind, args, kwargs,
                extract_input, extract_result, extract_metadata, cached_sig, static_attributes,
            )
        invocation_index = session._replay_cursor.get(name, 0) + 1
        if session.replay_plan.should_stub(name, invocation_index):
            return session.stub_result(name, kind)
        return _live_cutpoint_call(
            session, fn, name, kind, args, kwargs,
            extract_input, invocation_index, cached_sig,
        )

    return wrapper


# --------------------------------------------------------------------------- #
# Recording (LIVE mode)
# --------------------------------------------------------------------------- #

def _apply_on_enter(session, name, kind, input, kwargs) -> tuple[dict, bool]:
    """Run ``on_enter`` if set. Returns ``(call_kwargs, entered)``.

    ``entered`` is True only when ``on_enter`` returned (so ``on_leave`` can pair).
    A raise from ``on_enter`` (e.g. TokenOps ``Halt``, a ``BaseException``) aborts
    before the wrapped function and does not mark entered.
    """
    call_kwargs = dict(kwargs)
    if session.on_enter is None:
        return call_kwargs, False
    patch = session.on_enter(name, kind, input)
    if patch:
        call_kwargs.update(dict(patch))
    return call_kwargs, True


def _run_on_leave(session, name, kind, input, entered: bool) -> None:
    if entered and session.on_leave is not None:
        session.on_leave(name, kind, input)


def _record_call(
    session, fn, name, kind, args, kwargs,
    extract_input, extract_result, extract_metadata, cached_sig=None, static_attributes=None,
):
    input = _capture_input(fn, kind, args, kwargs, extract_input, cached_sig)
    call_kwargs, entered = _apply_on_enter(session, name, kind, input, kwargs)
    # Open the span before the body so nested boundaries parent here (OTel Context).
    span_id, parent_id = session.start_span()
    try:
        try:
            result = fn(*args, **call_kwargs)
        except Exception as exc:
            _record_failure(
                session, name, kind, input, exc, static_attributes,
                envelope_id=span_id, parent_envelope_id=parent_id,
            )
            raise
        _record_success(
            session, name, kind, input, result, extract_result, extract_metadata,
            static_attributes,
            envelope_id=span_id, parent_envelope_id=parent_id,
        )
        return result
    finally:
        session.end_span()
        _run_on_leave(session, name, kind, input, entered)


async def _record_call_async(
    session, fn, name, kind, args, kwargs,
    extract_input, extract_result, extract_metadata, cached_sig=None, static_attributes=None,
):
    input = _capture_input(fn, kind, args, kwargs, extract_input, cached_sig)
    call_kwargs, entered = _apply_on_enter(session, name, kind, input, kwargs)
    span_id, parent_id = session.start_span()
    try:
        try:
            result = await fn(*args, **call_kwargs)
        except Exception as exc:
            _record_failure(
                session, name, kind, input, exc, static_attributes,
                envelope_id=span_id, parent_envelope_id=parent_id,
            )
            raise
        _record_success(
            session, name, kind, input, result, extract_result, extract_metadata,
            static_attributes,
            envelope_id=span_id, parent_envelope_id=parent_id,
        )
        return result
    finally:
        session.end_span()
        _run_on_leave(session, name, kind, input, entered)


def _record_success(
    session, name, kind, input, result, extract_result, extract_metadata,
    static_attributes=None,
    *,
    envelope_id: str | None = None,
    parent_envelope_id: str | None = None,
):
    """Record the envelope, then notify observers. Never touches the return value."""
    recorded = extract_result(result) if extract_result else result
    output = result_to_output(recorded, kind)
    attributes = _call_attributes(recorded, kind, extract_metadata, static_attributes)
    session.record_envelope(
        name, kind, input, output,
        envelope_id=envelope_id, parent_envelope_id=parent_envelope_id,
        attributes=attributes,
    )
    if session.on_crossing is not None:
        session.on_crossing(name, kind, input, result)


def _record_failure(
    session, name, kind, input, exc, static_attributes=None,
    *,
    envelope_id: str | None = None,
    parent_envelope_id: str | None = None,
):
    """Record a failed crossing so incidents that raise are still reproducible."""
    session.record_envelope(
        name, kind, input, Output(),
        envelope_id=envelope_id, parent_envelope_id=parent_envelope_id,
        status=Status(code="ERROR", message=str(exc)),
        attributes={**(static_attributes or {}), "error.type": type(exc).__name__},
    )


def _call_attributes(result, kind, extract_metadata, static_attributes):
    """The GenAI attributes for this crossing: model and sampling params.

    Model attributes only apply to ``llm`` boundaries, so tool and router results are
    not scraped for a stray ``model`` key. An explicit extract_metadata hook always wins
    and works for any kind. A method boundary contributes its own inferred schema
    (``static_attributes``). Capture is best-effort and never raises.
    """
    attributes = dict(static_attributes) if static_attributes else {}
    try:
        model = sampling = None
        if extract_metadata is not None:
            source = extract_metadata(result)
            model, sampling = model_from(source), sampling_params_from(source)
        elif kind == "llm":
            model, sampling = model_from(result), sampling_params_from(result)
        if model or sampling:
            request = LLMRequest(model=model, sampling=sampling or SamplingParams())
            attributes.update(request.to_attributes())
    except Exception:
        pass
    return attributes


# --------------------------------------------------------------------------- #
# Cut-point (REPLAY mode, live boundary). No envelope; capture for assertions.
# --------------------------------------------------------------------------- #

def _live_cutpoint_call(
    session, fn, name, kind, args, kwargs, extract_input, invocation_index, cached_sig=None,
):
    input = _capture_input(fn, kind, args, kwargs, extract_input, cached_sig)
    session.capture_live_input(name, invocation_index, input)
    call_kwargs, entered = _apply_on_enter(session, name, kind, input, kwargs)
    try:
        try:
            result = fn(*args, **call_kwargs)
        except Exception:
            _advance_cutpoint(session, name, invocation_index)
            raise
        _finish_cutpoint(session, name, kind, input, result, invocation_index)
        return result
    finally:
        _run_on_leave(session, name, kind, input, entered)


async def _live_cutpoint_call_async(
    session, fn, name, kind, args, kwargs, extract_input, invocation_index, cached_sig=None,
):
    input = _capture_input(fn, kind, args, kwargs, extract_input, cached_sig)
    session.capture_live_input(name, invocation_index, input)
    call_kwargs, entered = _apply_on_enter(session, name, kind, input, kwargs)
    try:
        try:
            result = await fn(*args, **call_kwargs)
        except Exception:
            _advance_cutpoint(session, name, invocation_index)
            raise
        _finish_cutpoint(session, name, kind, input, result, invocation_index)
        return result
    finally:
        _run_on_leave(session, name, kind, input, entered)


def _finish_cutpoint(session, name, kind, input, result, invocation_index):
    session.capture_live_result(name, invocation_index, result)
    _advance_cutpoint(session, name, invocation_index)
    if session.on_crossing is not None:
        session.on_crossing(name, kind, input, result)


def _advance_cutpoint(session, name, invocation_index):
    session.next_invocation(name)
    session._replay_cursor[name] = invocation_index


# --------------------------------------------------------------------------- #
# Zero-config input capture: bind the real signature, record args by name.
# --------------------------------------------------------------------------- #

_IO_KEYS = ("messages", "system_prompt", "rag_chunks")


def _capture_input(fn, kind, args, kwargs, extract_input, cached_sig=None) -> Input:
    if extract_input is not None:
        return extract_input(*args, **kwargs)
    # The default capture must never break the wrapped call.
    try:
        return _bind_input(fn, kind, args, kwargs, cached_sig)
    except Exception:
        return Input(arguments={"args": _json_safe(list(args)), "kwargs": _json_safe(dict(kwargs))})


def _bind_input(fn, kind, args, kwargs, cached_sig=None) -> Input:
    arguments = _bound_arguments(fn, args, kwargs, cached_sig)
    messages: list[Message] = []
    if kind == "llm":
        source = _io_source(arguments)
        rows = source.get("messages") or []
        if not rows and "user_message" in source:
            rows = [{"role": "user", "content": source["user_message"]}]
        messages = [_message(row) for row in rows]
    return Input.model_construct(arguments=arguments, messages=messages)


def _message(row: Any) -> Message:
    """A typed chat message from a captured row; anything that is not a mapping is kept
    as the content of an unknown-role message rather than dropped."""
    if isinstance(row, Mapping):
        return Message.model_construct(**{"role": "", "content": None, **dict(row)})
    return Message.model_construct(role="unknown", content=_json_safe(row))


def _bound_arguments(fn, args, kwargs, cached_sig=None) -> dict[str, Any]:
    """Record the call by real parameter names. Skip self/cls, flatten **kwargs.

    Falls back to positional capture when the callable has no introspectable
    signature (some builtins / C callables).
    """
    sig = cached_sig
    try:
        if sig is None:
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
    # Prefer full structured dumps so tool_calls / name / id are not stripped.
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: _json_safe(getattr(value, f.name), _depth + 1)
            for f in dataclasses.fields(value)
        }
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump()
        except Exception:
            return repr(value)
    # Duck-typed chat message: keep every public attribute, not just role/content.
    role = getattr(value, "role", None)
    content = getattr(value, "content", None)
    if isinstance(role, str) and isinstance(content, str):
        data = getattr(value, "__dict__", None)
        if isinstance(data, dict) and data:
            return {
                str(k): _json_safe(v, _depth + 1)
                for k, v in data.items()
                if not str(k).startswith("_")
            }
        return {"role": role, "content": content}
    return repr(value)
