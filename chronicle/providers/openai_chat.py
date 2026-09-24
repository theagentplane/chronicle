"""OpenAI Chat Completions adapter (also LiteLLM / vLLM / Ollama OpenAI endpoint).

Request: ``messages[]`` (system prompt is a ``role="system"`` message, content is
a string or a list of parts), ``model``, sampling keys, ``tools[{type:function,
function:{name, description, parameters}}]``.

Response: ``choices[0].message{content, tool_calls[{id, function:{name,
arguments: JSON-string}}]}``, ``choices[0].finish_reason`` (stop/length/
tool_calls), ``usage{prompt_tokens, completion_tokens}``, ``model`` echo.
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


class OpenAIChatProvider:
    name = "openai"

    def parse_request(self, kwargs: Mapping[str, Any]) -> tuple[LLMRequest, list[Message]]:
        try:
            data = dict(kwargs) if isinstance(kwargs, Mapping) else {}
            request = base_request(data, "openai")
            rows = data.get("messages", [])
            return request, coerce_messages(rows)
        except Exception:
            return LLMRequest(provider="openai"), []

    def parse_response(self, response: Any) -> tuple[LLMOutput, str | None]:
        try:
            message = get_path(response, "choices", 0, "message")
            text = get_field(message, "content") if message is not None else None
            if isinstance(text, list):  # content parts list -> join text parts
                text = (
                    "".join(
                        str(get_field(p, "text", ""))
                        for p in text
                        if isinstance(p, (Mapping, object))
                    )
                    or None
                )
            tool_calls = self._tool_calls(message)
            finish = get_path(response, "choices", 0, "finish_reason")
            usage = coerce_usage(get_field(response, "usage"))
            model = get_field(response, "model")
            return (
                LLMOutput(text=text, tool_calls=tool_calls, finish_reason=finish, usage=usage),
                str(model) if model else None,
            )
        except Exception:
            return LLMOutput(), None

    @staticmethod
    def _tool_calls(message: Any) -> list[ToolCall]:
        raw = get_field(message, "tool_calls") if message is not None else None
        if not isinstance(raw, (list, tuple)):
            return []
        out: list[ToolCall] = []
        for item in raw:
            try:
                fn = get_field(item, "function") or {}
                out.append(
                    ToolCall.model_construct(
                        id=get_field(item, "id"),
                        name=get_field(fn, "name", "") or "",
                        arguments=coerce_tool_arguments(get_field(fn, "arguments")),
                    )
                )
            except Exception:
                continue
        return out
