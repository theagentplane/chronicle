"""Drop-in wrappers, so you can start recording with no decorators.

- ``wrap(client)`` records every model call an OpenAI- or Anthropic-style client
  makes. One line to adopt; in replay it returns the recorded response and makes
  no API call.
- ``instrument_langgraph(nodes)`` wraps every graph node as a ``@boundary`` in one
  call, so LangGraph users do not decorate each node by hand.

Both feed the same record / replay / cut-point session as ``@boundary``, so there
is nothing new to learn: same envelopes, same ``ReplayPlan``, same ``on_crossing``.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Mapping
from typing import Any

from chronicle.boundary import boundary
from chronicle.envelope.schema import ActionResult, InputState
from chronicle.session import SessionMode, get_session, sampling_params_from


def instrument_langgraph(nodes: Mapping[str, Callable], *, kind: str = "custom") -> dict[str, Callable]:
    """Wrap every LangGraph node as a ``@boundary`` in one call.

        graph = StateGraph(State)
        for name, fn in chronicle.instrument_langgraph({"agent": agent, "tools": tool_node}).items():
            graph.add_node(name, fn)

    Each node keeps its behavior (transparent) and gains record / stub-replay /
    cut-point. Async nodes are supported. Use ``kind="llm"`` for nodes that call a
    model so their envelopes capture model metadata.
    """
    return {name: boundary(name, kind=kind)(fn) for name, fn in nodes.items()}


def wrap(client: Any, *, boundary_id: str = "llm") -> Any:
    """Record every model call an OpenAI- or Anthropic-style client makes.

        client = chronicle.wrap(OpenAI())
        client.chat.completions.create(model="gpt-4o", messages=[...])  # recorded

    Wraps the client's completion method in place and returns the client. It is
    transparent in live mode (you get the real response); in replay mode it returns
    the recorded response with attribute/index access (``resp.choices[0].message
    .content``) and makes no API call. For a bare callable, use ``wrap_llm``.
    """
    target = _completion_target(client)
    if target is None:
        raise TypeError(
            "chronicle.wrap expected an OpenAI-style client (.chat.completions.create) "
            "or an Anthropic-style client (.messages.create). Use wrap_llm for other callables."
        )
    owner, attr, original = target
    setattr(owner, attr, _wrap_completion(original, boundary_id))
    return client


def _completion_target(client: Any):
    completions = getattr(getattr(client, "chat", None), "completions", None)
    if completions is not None and callable(getattr(completions, "create", None)):
        return completions, "create", completions.create
    messages = getattr(client, "messages", None)
    if messages is not None and callable(getattr(messages, "create", None)):
        return messages, "create", messages.create
    return None


def _wrap_completion(create: Callable, boundary_id: str) -> Callable:
    if inspect.iscoroutinefunction(create):
        @functools.wraps(create)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            session = get_session()
            input_state = _input_state(kwargs)
            if session.mode is SessionMode.REPLAY and _should_stub(session, boundary_id):
                return _stub(session, boundary_id)
            result = await create(*args, **kwargs)
            _observe(session, boundary_id, input_state, result, kwargs)
            return result

        return async_wrapper

    @functools.wraps(create)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        session = get_session()
        input_state = _input_state(kwargs)
        if session.mode is SessionMode.REPLAY and _should_stub(session, boundary_id):
            return _stub(session, boundary_id)
        result = create(*args, **kwargs)
        _observe(session, boundary_id, input_state, result, kwargs)
        return result

    return wrapper


def _should_stub(session, boundary_id: str) -> bool:
    invocation_index = session._replay_cursor.get(boundary_id, 0) + 1
    return session.replay_plan.should_stub(boundary_id, invocation_index)


def _observe(session, boundary_id, input_state, response, request_kwargs):
    """Record in LIVE, or capture as a live cut-point in REPLAY. Never mutates the
    response; the caller always gets the real object."""
    completion, model, usage = _extract(response)
    if session.mode is SessionMode.REPLAY:
        idx = session._replay_cursor.get(boundary_id, 0) + 1
        session.capture_live_input(boundary_id, idx, input_state)
        session.capture_live_result(boundary_id, idx, response)
        session.next_invocation(boundary_id)
        session._replay_cursor[boundary_id] = idx
    else:
        action = ActionResult(
            completion=completion,
            token_usage=_int_usage(usage),
            raw_response=_raw(response),
        )
        session.record_envelope(
            boundary_id, "llm", input_state, action,
            model_version=model, sampling_params=sampling_params_from(request_kwargs),
        )
    if session.on_crossing is not None:
        session.on_crossing(boundary_id, "llm", input_state, response)


def _stub(session, boundary_id: str) -> Any:
    envelope = session._fixture_for(boundary_id)
    raw = envelope.action_result.raw_response
    return _Recorded(raw) if raw is not None else envelope.action_result.completion


def _input_state(kwargs: Mapping[str, Any]) -> InputState:
    from chronicle.boundary import _json_safe

    return InputState(
        messages=_json_safe(list(kwargs.get("messages", []))),
        system_prompt=kwargs.get("system") or kwargs.get("system_prompt"),
        graph_state=_json_safe(dict(kwargs)),
    )


def _extract(response: Any):
    completion = _first(
        lambda: response.choices[0].message.content,           # OpenAI chat
        lambda: response.content[0].text,                      # Anthropic messages
        lambda: response["choices"][0]["message"]["content"],  # dict-shaped
    )
    model = getattr(response, "model", None) or _get(response, "model")
    usage = getattr(response, "usage", None)
    if usage is None:
        usage = _get(response, "usage")
    return completion, model, usage


def _raw(response: Any) -> dict[str, Any] | None:
    if hasattr(response, "model_dump"):
        try:
            return response.model_dump()
        except Exception:
            return None
    if isinstance(response, Mapping):
        return dict(response)
    return None


def _int_usage(usage: Any) -> dict[str, int]:
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        try:
            usage = usage.model_dump()
        except Exception:
            return {}
    if isinstance(usage, Mapping):
        return {str(k): int(v) for k, v in usage.items() if isinstance(v, int) and not isinstance(v, bool)}
    return {}


def _first(*fns):
    for fn in fns:
        try:
            value = fn()
        except (AttributeError, IndexError, KeyError, TypeError):
            continue
        if value is not None:
            return value
    return None


def _get(obj: Any, key: str):
    if isinstance(obj, Mapping):
        return obj.get(key)
    return None


class _Recorded:
    """Read-only attribute and index access over a recorded response dict, so a
    replayed call returns something shaped like the provider's response object
    (e.g. ``resp.choices[0].message.content``)."""

    __slots__ = ("_data",)

    def __init__(self, data: Any) -> None:
        object.__setattr__(self, "_data", data)

    def __getattr__(self, name: str) -> Any:
        data = object.__getattribute__(self, "_data")
        if isinstance(data, Mapping) and name in data:
            return _recorded(data[name])
        raise AttributeError(name)

    def __getitem__(self, key: Any) -> Any:
        return _recorded(object.__getattribute__(self, "_data")[key])

    def __repr__(self) -> str:
        return f"Recorded({object.__getattribute__(self, '_data')!r})"


def _recorded(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _Recorded(value)
    if isinstance(value, list):
        return [_recorded(v) for v in value]
    return value
