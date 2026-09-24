"""Anthropic Messages adapter.

Request: top-level ``system`` (string or blocks), ``messages[]`` (content is a
string or typed blocks), ``model``, sampling keys, ``tools[{name, description,
input_schema}]``.

Response: ``content[]`` blocks (``{type:text, text}`` or ``{type:tool_use, id,
name, input: dict}``), ``stop_reason`` (end_turn/max_tokens/tool_use — mapped
to stop/length/tool_calls), ``usage{input_tokens, output_tokens}``, ``model``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from chronicle.envelope.genai import LLMRequest
from chronicle.envelope.schema import LLMOutput, Message, ToolCall
from chronicle.providers import base_request, coerce_tool_arguments, coerce_usage, get_field

_STOP_MAP = {
    "end_turn": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "stop_sequence": "stop",
}


class AnthropicProvider:
    name = "anthropic"

    def parse_request(self, kwargs: Mapping[str, Any]) -> tuple[LLMRequest, list[Message]]:
        try:
            data = dict(kwargs) if isinstance(kwargs, Mapping) else {}
            request = base_request(data, "anthropic")
            messages = self._messages(data)
            return request, messages
        except Exception:
            return LLMRequest(provider="anthropic"), []

    def parse_response(self, response: Any) -> tuple[LLMOutput, str | None]:
        try:
            blocks = get_field(response, "content")
            texts: list[str] = []
            tool_calls: list[ToolCall] = []
            if isinstance(blocks, (list, tuple)):
                for block in blocks:
                    btype = get_field(block, "type")
                    if btype == "tool_use":
                        try:
                            tool_calls.append(
                                ToolCall.model_construct(
                                    id=get_field(block, "id"),
                                    name=get_field(block, "name", "") or "",
                                    arguments=coerce_tool_arguments(get_field(block, "input")),
                                )
                            )
                        except Exception:
                            continue
                    elif btype == "text":
                        chunk = get_field(block, "text")
                        if isinstance(chunk, str):
                            texts.append(chunk)
            raw_stop = get_field(response, "stop_reason")
            finish = _STOP_MAP.get(str(raw_stop), str(raw_stop) if raw_stop else None)
            usage = coerce_usage(get_field(response, "usage"))
            model = get_field(response, "model")
            text = "".join(texts) or None
            return LLMOutput(text=text, tool_calls=tool_calls, finish_reason=finish, usage=usage), (
                str(model) if model else None
            )
        except Exception:
            return LLMOutput(), None

    @staticmethod
    def _messages(data: Mapping[str, Any]) -> list[Message]:
        out: list[Message] = []
        try:
            system = data.get("system")
            if isinstance(system, str) and system:
                out.append(Message.model_construct(role="system", content=system))
            elif isinstance(system, list) and system:
                joined = "".join(
                    str(b.get("text", ""))
                    for b in system
                    if isinstance(b, Mapping) and b.get("type") == "text"
                )
                out.append(Message.model_construct(role="system", content=joined or system))
            for row in data.get("messages", []) or []:
                if isinstance(row, Mapping):
                    content = row.get("content")
                    if isinstance(content, list):  # typed blocks -> flatten text parts
                        flat = " ".join(
                            str(p.get("text", ""))
                            for p in content
                            if isinstance(p, Mapping) and p.get("type") == "text"
                        )
                        row = {**row, "content": flat or content}
                    out.append(
                        Message.model_construct(**{"role": "", "content": None, **dict(row)})
                    )
        except Exception:
            pass
        return out
