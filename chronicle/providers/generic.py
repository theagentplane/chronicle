"""Generic dict adapter: keeps today's convention, never raises.

This is the behavior-preserving refactor of ``chronicle/wrap.py::_extract``:
a plain dict (or object) carrying ``completion``, ``tool_calls``,
``finish_reason`` and ``usage``/``token_usage``. Unknown providers and
malformed responses fall back here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from chronicle.envelope.genai import LLMRequest
from chronicle.envelope.schema import LLMOutput, Message, ToolCall
from chronicle.providers import (
    base_request,
    coerce_messages,
    coerce_tool_arguments,
    coerce_usage,
    get_field,
    get_path,
)


class GenericProvider:
    name = "generic"

    def parse_request(self, kwargs: Mapping[str, Any]) -> tuple[LLMRequest, list[Message]]:
        try:
            request = base_request(kwargs if isinstance(kwargs, Mapping) else {}, "generic")
            rows: Any = []
            if isinstance(kwargs, Mapping):
                rows = kwargs.get("messages", [])
                if not rows and kwargs.get("user_message"):
                    rows = [{"role": "user", "content": kwargs.get("user_message")}]
            return request, coerce_messages(rows)
        except Exception:
            return LLMRequest(provider="generic"), []

    def parse_response(self, response: Any) -> tuple[LLMOutput, str | None]:
        try:
            # Today's heuristic, in order: OpenAI-shape, Anthropic-shape, dict-shape.
            text = _first_text(response)
            tool_calls = _tool_calls(response)
            finish = _first_value(
                lambda: (
                    get_path(response, "choices", 0, "message", "finish_reason")
                    or get_path(response, "choices", 0, "finish_reason")
                ),
                lambda: get_field(response, "stop_reason"),
                lambda: get_field(response, "finish_reason"),
            )
            usage_raw = get_field(response, "usage")
            if usage_raw is None and isinstance(response, Mapping):
                usage_raw = response.get("token_usage", response.get("usage"))
            usage = coerce_usage(usage_raw)
            model = get_field(response, "model_version") or get_field(response, "model")
            model_str = str(model) if model else None
            return LLMOutput(
                text=text, tool_calls=tool_calls, finish_reason=finish, usage=usage
            ), model_str
        except Exception:
            return LLMOutput(), None


def _first_text(response: Any) -> str | None:
    return _first_value(
        lambda: get_path(response, "choices", 0, "message", "content"),
        lambda: get_path(response, "content", 0, "text"),
        lambda: get_field(response, "completion"),
        lambda: get_field(response, "text"),
    )


def _tool_calls(response: Any) -> list[ToolCall]:
    raw: Any = None
    # OpenAI object shape
    candidate = get_path(response, "choices", 0, "message", "tool_calls")
    if candidate:
        raw = candidate
    # Anthropic content blocks with type == tool_use
    if raw is None:
        blocks = get_field(response, "content")
        if isinstance(blocks, (list, tuple)):
            found = [b for b in blocks if get_field(b, "type") == "tool_use"]
            if found:
                raw = found
    # Plain dict convention
    if raw is None:
        raw = get_field(response, "tool_calls")
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[ToolCall] = []
    for item in raw:
        try:
            fn = get_field(item, "function")
            if fn is not None:  # OpenAI: {id, function:{name, arguments}}
                name = get_field(fn, "name", "") or ""
                args = coerce_tool_arguments(get_field(fn, "arguments"))
                call_id = get_field(item, "id")
            else:  # Anthropic block or flat dict
                name = get_field(item, "name", "") or ""
                args = coerce_tool_arguments(get_field(item, "input", get_field(item, "arguments")))
                call_id = get_field(item, "id")
            out.append(ToolCall.model_construct(id=call_id, name=name, arguments=args))
        except Exception:
            continue
    return out


def _first_value(*fns) -> Any:
    for fn in fns:
        try:
            value = fn()
        except (AttributeError, IndexError, KeyError, TypeError):
            continue
        if value is not None:
            return value
    return None
