"""OpenAI Responses API adapter.

Why this one as the third adapter: same ``openai`` SDK family (zero new
dependency), but a genuinely different shape — so it proves the Provider
protocol handles same-vendor-different-API without special-casing downstream.

Request: top-level ``instructions`` (system prompt), ``input`` (a string or a
list of items), ``model``, sampling keys, flat
``tools[{type:function, name, description, parameters}]``.

Response: ``output[]`` items (``{type:message, content[{text}]}`` or
``{type:function_call, call_id, name, arguments: JSON-string}``), ``status``
(``completed``/``incomplete`` + ``incomplete_details{reason}`` — mapped to
stop/length/tool_calls), ``usage{input_tokens, output_tokens}``, ``model``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from chronicle.envelope.genai import LLMRequest
from chronicle.envelope.schema import LLMOutput, Message, ToolCall
from chronicle.providers import base_request, coerce_tool_arguments, coerce_usage, get_field

_STATUS_MAP = {"completed": "stop", "incomplete": "length", "failed": "stop", "cancelled": "stop"}


class OpenAIResponsesProvider:
    name = "openai_responses"

    def parse_request(self, kwargs: Mapping[str, Any]) -> tuple[LLMRequest, list[Message]]:
        try:
            data = dict(kwargs) if isinstance(kwargs, Mapping) else {}
            request = base_request(data, "openai_responses")
            messages = self._messages(data)
            return request, messages
        except Exception:
            return LLMRequest(provider="openai_responses"), []

    def parse_response(self, response: Any) -> tuple[LLMOutput, str | None]:
        try:
            items = get_field(response, "output")
            texts: list[str] = []
            tool_calls: list[ToolCall] = []
            if isinstance(items, (list, tuple)):
                for item in items:
                    itype = get_field(item, "type")
                    if itype == "function_call":
                        try:
                            tool_calls.append(
                                ToolCall.model_construct(
                                    id=get_field(item, "call_id", get_field(item, "id")),
                                    name=get_field(item, "name", "") or "",
                                    arguments=coerce_tool_arguments(get_field(item, "arguments")),
                                )
                            )
                        except Exception:
                            continue
                    elif itype == "message":
                        for part in get_field(item, "content") or []:
                            chunk = get_field(part, "text")
                            if isinstance(chunk, str):
                                texts.append(chunk)
                    elif itype in ("reasoning", "text"):
                        chunk = get_field(item, "text")
                        if isinstance(chunk, str):
                            texts.append(chunk)
            # finish: explicit function calls win; else map status/details.
            if tool_calls:
                finish: str | None = "tool_calls"
            else:
                status = get_field(response, "status")
                details = get_field(response, "incomplete_details") or {}
                reason = (
                    get_field(details, "reason") if isinstance(details, (Mapping, object)) else None
                )
                if reason == "max_output_tokens":
                    finish = "length"
                elif status in _STATUS_MAP:
                    finish = _STATUS_MAP[status]
                else:
                    finish = get_field(response, "finish_reason")
            usage = coerce_usage(get_field(response, "usage"))
            model = get_field(response, "model")
            return (
                LLMOutput(
                    text="".join(texts) or None,
                    tool_calls=tool_calls,
                    finish_reason=finish,
                    usage=usage,
                ),
                str(model) if model else None,
            )
        except Exception:
            return LLMOutput(), None

    @staticmethod
    def _messages(data: Mapping[str, Any]) -> list[Message]:
        out: list[Message] = []
        try:
            instructions = data.get("instructions")
            if isinstance(instructions, str) and instructions:
                out.append(Message.model_construct(role="system", content=instructions))
            raw = data.get("input", data.get("messages", []))
            if isinstance(raw, str):
                out.append(Message.model_construct(role="user", content=raw))
            elif isinstance(raw, (list, tuple)):
                for entry in raw:
                    if isinstance(entry, Mapping):
                        entry_type = entry.get("type")
                        if entry_type == "message":
                            role = str(entry.get("role", "user"))
                            flat = " ".join(
                                str(p.get("text", ""))
                                for p in entry.get("content", [])
                                if isinstance(p, Mapping)
                            )
                            out.append(
                                Message.model_construct(
                                    role=role, content=flat or entry.get("content")
                                )
                            )
                        elif "role" in entry or "content" in entry:
                            out.append(
                                Message.model_construct(
                                    **{"role": "", "content": None, **dict(entry)}
                                )
                            )
                    elif isinstance(entry, str):
                        out.append(Message.model_construct(role="user", content=entry))
        except Exception:
            pass
        return out
