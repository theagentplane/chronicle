"""The Anthropic-style adapter: Messages API.

Design section 4.3. Conventions it converts (golden cases in ``tests/providers/anthropic``):

- ``tool_use`` blocks carry ``input`` as an object already; ``thinking`` blocks map to
  ``reasoning`` blocks.
- Cached tokens are reported **separately** (``cache_read_input_tokens`` and
  ``cache_creation_input_tokens``) and ``input_tokens`` is already the non-cached part, so the
  buckets map one to one. Anthropic does not report reasoning tokens separately: thinking tokens
  are inside ``output_tokens`` and ``usage.reasoning`` is 0.
- ``stop_reason`` maps ``end_turn`` and ``stop_sequence`` to ``stop``, ``max_tokens`` to
  ``length``, ``tool_use`` to ``tool_calls``, ``refusal`` to ``content_filter`` and anything
  else to ``other``. The original value stays in ``output.raw``. The ``refusal`` mapping is a
  proposal to be confirmed in review (issue #67).
- When ``stop_reason`` is ``refusal`` the text blocks of the response are emitted as ``refusal``
  blocks, so a refusal reads the same as an OpenAI ``message.refusal``.
- A ``tool_result`` block inside a user message is mapped to a ``tool`` message.
"""

from agentplane_primitives.enums import FinishReason, MessageRole, ModelSource
from agentplane_primitives.models import (
    ContentBlock,
    LlmInput,
    LlmOutput,
    Message,
    ReasoningBlock,
    RefusalBlock,
    TextBlock,
    ToolCallBlock,
    Usage,
)
from pydantic import JsonValue

from chronicle.framework.adapters.json_access_utils import as_dict, as_int, as_list, as_str
from chronicle.framework.adapters.llm_params_utils import params_from_arguments
from chronicle.framework.adapters.openai_adapter import UNKNOWN_MODEL

_FINISH = {
    "end_turn": FinishReason.STOP,
    "stop_sequence": FinishReason.STOP,
    "max_tokens": FinishReason.LENGTH,
    "tool_use": FinishReason.TOOL_CALLS,
    "refusal": FinishReason.CONTENT_FILTER,
}


class AnthropicAdapter:
    """Adapter for Anthropic Messages shaped requests and responses."""

    provider = "anthropic"

    # ---- input -------------------------------------------------------------------------

    def to_canonical_input(self, raw: dict[str, JsonValue]) -> LlmInput:
        messages: list[Message] = []
        for item in as_list(raw.get("messages")):
            messages.extend(_messages(item))
        response_format = raw.get("response_format")
        return LlmInput(
            model=as_str(raw.get("model")) or UNKNOWN_MODEL,
            messages=messages,
            system=_system(raw.get("system")),
            tools=_tools(raw.get("tools")),
            tool_choice=_tool_choice(raw.get("tool_choice")),
            response_format=response_format if isinstance(response_format, dict) else None,
            params=params_from_arguments(raw),
            raw=raw,
        )

    # ---- output ------------------------------------------------------------------------

    def to_canonical_output(self, raw: JsonValue, requested_model: str | None) -> LlmOutput:
        data = as_dict(raw)
        stop_reason = data.get("stop_reason")
        refused = stop_reason == "refusal"

        content: list[ContentBlock] = []
        for block in as_list(data.get("content")):
            converted = _output_block(block, refused)
            if converted is not None:
                content.append(converted)
        if refused and not any(isinstance(b, RefusalBlock) for b in content):
            content.append(RefusalBlock(text=""))

        served = as_str(data.get("model"))
        model = served or requested_model
        usage = data.get("usage")
        return LlmOutput(
            content=content,
            finish_reason=(
                _FINISH.get(stop_reason, FinishReason.OTHER)
                if isinstance(stop_reason, str)
                else None
            ),
            provider=self.provider,
            model=model,
            model_source=(
                None if model is None else (ModelSource.SERVED if served else ModelSource.REQUESTED)
            ),
            usage=_usage(usage) if isinstance(usage, dict) else None,
            response_id=as_str(data.get("id")),
            raw=raw,
        )


def _usage(usage: dict[str, JsonValue]) -> Usage:
    return Usage(
        input=as_int(usage.get("input_tokens")),
        cached_read=as_int(usage.get("cache_read_input_tokens")),
        cache_write=as_int(usage.get("cache_creation_input_tokens")),
        output=as_int(usage.get("output_tokens")),
        reasoning=0,
    )


def _output_block(block: JsonValue, refused: bool) -> ContentBlock | None:
    data = as_dict(block)
    kind = data.get("type")
    if kind == "text" and isinstance(data.get("text"), str):
        text = str(data["text"])
        return RefusalBlock(text=text) if refused else TextBlock(text=text)
    if kind == "tool_use":
        name = as_str(data.get("name"))
        if name is None:
            return None
        return ToolCallBlock(
            id=as_str(data.get("id")), name=name, arguments=as_dict(data.get("input"))
        )
    if kind == "thinking" and isinstance(data.get("thinking"), str):
        return ReasoningBlock(text=str(data["thinking"]))
    return None


def _system(system: JsonValue) -> str | None:
    if isinstance(system, str):
        return system or None
    texts = [
        str(as_dict(part).get("text"))
        for part in as_list(system)
        if isinstance(as_dict(part).get("text"), str)
    ]
    return "\n".join(texts) or None


def _messages(item: JsonValue) -> list[Message]:
    data = as_dict(item)
    role = {"user": MessageRole.USER, "assistant": MessageRole.ASSISTANT}.get(str(data.get("role")))
    if role is None:
        return []
    content = data.get("content")
    if isinstance(content, str):
        return [Message(role=role, content=content)]
    blocks: list[ContentBlock] = []
    results: list[Message] = []
    for part in as_list(content):
        part_data = as_dict(part)
        kind = part_data.get("type")
        if kind == "text" and isinstance(part_data.get("text"), str):
            blocks.append(TextBlock(text=str(part_data["text"])))
        elif kind == "tool_use":
            name = as_str(part_data.get("name"))
            if name is not None:
                blocks.append(
                    ToolCallBlock(
                        id=as_str(part_data.get("id")),
                        name=name,
                        arguments=as_dict(part_data.get("input")),
                    )
                )
        elif kind == "thinking" and isinstance(part_data.get("thinking"), str):
            blocks.append(ReasoningBlock(text=str(part_data["thinking"])))
        elif kind == "tool_result":
            results.append(
                Message(
                    role=MessageRole.TOOL,
                    content=_tool_result_text(part_data.get("content")),
                    tool_call_id=as_str(part_data.get("tool_use_id")),
                )
            )
    messages: list[Message] = []
    if blocks:
        messages.append(Message(role=role, content=blocks))
    messages.extend(results)
    return messages


def _tool_result_text(content: JsonValue) -> str:
    if isinstance(content, str):
        return content
    texts = [
        str(as_dict(part).get("text"))
        for part in as_list(content)
        if isinstance(as_dict(part).get("text"), str)
    ]
    return "\n".join(texts)


def _tools(tools: JsonValue) -> list[dict[str, JsonValue]] | None:
    if not isinstance(tools, list):
        return None
    result: list[dict[str, JsonValue]] = []
    for tool in tools:
        data = as_dict(tool)
        name = as_str(data.get("name"))
        if name is None:
            continue
        entry: dict[str, JsonValue] = {"name": name}
        description = as_str(data.get("description"))
        if description is not None:
            entry["description"] = description
        schema = data.get("input_schema")
        if isinstance(schema, dict):
            entry["parameters"] = schema
        result.append(entry)
    return result


def _tool_choice(choice: JsonValue) -> JsonValue:
    data = as_dict(choice)
    kind = data.get("type")
    if kind == "auto":
        return "auto"
    if kind == "any":
        return "required"
    if kind == "none":
        return "none"
    if kind == "tool":
        name = as_str(data.get("name"))
        return {"name": name} if name else None
    return None
