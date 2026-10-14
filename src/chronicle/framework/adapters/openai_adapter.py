"""The OpenAI-style adapter: Chat Completions (also covers Azure OpenAI and LiteLLM).

Design section 4.3. LiteLLM returns OpenAI-shaped responses, so one adapter serves all three; the
``provider`` name differs and is chosen by whoever builds the adapter.

Conventions it converts (golden cases in ``tests/providers/openai``):

- Tool call ``arguments`` arrive as a JSON **string** and are parsed; text that is not a JSON
  object is kept under the key ``$raw_arguments``.
- Cached tokens are counted **inside** ``prompt_tokens``; they are subtracted so ``input`` is the
  non-cached part. Reasoning tokens are counted inside ``completion_tokens``; they are subtracted
  so ``output`` is the non-reasoning part. The buckets are exclusive and additive.
- ``message.refusal`` becomes a ``refusal`` block. The provider's own ``finish_reason`` stays in
  ``output.raw``; the canonical one is mapped (unknown values become ``other``).
- Only the first choice is read; any further choices stay in ``raw``.
"""

import json

from agentplane_primitives.enums import FinishReason, MessageRole, ModelSource
from agentplane_primitives.models import (
    ContentBlock,
    LlmInput,
    LlmOutput,
    Message,
    RefusalBlock,
    TextBlock,
    ToolCallBlock,
    Usage,
)
from pydantic import JsonValue

from chronicle.framework.adapters.json_access_utils import as_dict, as_int, as_list, as_str
from chronicle.framework.adapters.llm_params_utils import params_from_arguments

UNKNOWN_MODEL = "unknown"
"""Written to ``input.model`` when the caller did not pass a model (the field is required)."""

_FINISH = {
    "stop": FinishReason.STOP,
    "length": FinishReason.LENGTH,
    "tool_calls": FinishReason.TOOL_CALLS,
    "function_call": FinishReason.TOOL_CALLS,
    "content_filter": FinishReason.CONTENT_FILTER,
}
_ROLES = {
    "system": MessageRole.SYSTEM,
    "developer": MessageRole.SYSTEM,
    "user": MessageRole.USER,
    "assistant": MessageRole.ASSISTANT,
    "tool": MessageRole.TOOL,
    "function": MessageRole.TOOL,
}


class OpenAiAdapter:
    """Adapter for OpenAI Chat Completions shaped requests and responses."""

    def __init__(self, provider: str = "openai") -> None:
        self.provider = provider

    # ---- input -------------------------------------------------------------------------

    def to_canonical_input(self, raw: dict[str, JsonValue]) -> LlmInput:
        messages = [m for m in (_message(item) for item in as_list(raw.get("messages"))) if m]
        response_format = raw.get("response_format")
        return LlmInput(
            model=as_str(raw.get("model")) or UNKNOWN_MODEL,
            messages=messages,
            tools=_tools(raw.get("tools")),
            tool_choice=_tool_choice(raw.get("tool_choice")),
            response_format=response_format if isinstance(response_format, dict) else None,
            params=params_from_arguments(raw),
            raw=raw,
        )

    # ---- output ------------------------------------------------------------------------

    def to_canonical_output(self, raw: JsonValue, requested_model: str | None) -> LlmOutput:
        data = as_dict(raw)
        choices = as_list(data.get("choices"))
        choice = as_dict(choices[0]) if choices else {}
        message = as_dict(choice.get("message"))

        content: list[ContentBlock] = []
        content.extend(_text_blocks(message.get("content")))
        refusal = as_str(message.get("refusal"))
        if refusal is not None:
            content.append(RefusalBlock(text=refusal))
        for call in as_list(message.get("tool_calls")):
            block = _tool_call(call)
            if block is not None:
                content.append(block)

        finish = choice.get("finish_reason")
        served = as_str(data.get("model"))
        model = served or requested_model
        usage = data.get("usage")
        return LlmOutput(
            content=content,
            finish_reason=_FINISH.get(finish, FinishReason.OTHER)
            if isinstance(finish, str)
            else None,
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
    prompt = as_int(usage.get("prompt_tokens"))
    completion = as_int(usage.get("completion_tokens"))
    cached = min(as_int(as_dict(usage.get("prompt_tokens_details")).get("cached_tokens")), prompt)
    reasoning = min(
        as_int(as_dict(usage.get("completion_tokens_details")).get("reasoning_tokens")),
        completion,
    )
    return Usage(
        input=prompt - cached,
        cached_read=cached,
        cache_write=0,
        output=completion - reasoning,
        reasoning=reasoning,
    )


def _text_blocks(content: JsonValue) -> list[ContentBlock]:
    if isinstance(content, str):
        return [TextBlock(text=content)] if content else []
    blocks: list[ContentBlock] = []
    for part in as_list(content):
        part_dict = as_dict(part)
        text = part_dict.get("text")
        if part_dict.get("type") in ("text", "output_text") and isinstance(text, str):
            blocks.append(TextBlock(text=text))
    return blocks


def _tool_call(call: JsonValue) -> ToolCallBlock | None:
    data = as_dict(call)
    function = as_dict(data.get("function"))
    name = as_str(function.get("name"))
    if name is None:
        return None
    arguments = function.get("arguments")
    parsed: dict[str, JsonValue]
    if isinstance(arguments, str):
        try:
            loaded = json.loads(arguments) if arguments else {}
        except ValueError:
            loaded = None
        parsed = loaded if isinstance(loaded, dict) else {"$raw_arguments": arguments}
    else:
        parsed = as_dict(arguments)
    return ToolCallBlock(id=as_str(data.get("id")), name=name, arguments=parsed)


def _message(item: JsonValue) -> Message | None:
    data = as_dict(item)
    role = _ROLES.get(str(data.get("role")))
    if role is None:
        return None
    blocks = _text_blocks(data.get("content"))
    for call in as_list(data.get("tool_calls")):
        block = _tool_call(call)
        if block is not None:
            blocks.append(block)
    content: str | list[ContentBlock]
    if blocks and all(isinstance(b, TextBlock) for b in blocks) and len(blocks) == 1:
        first = blocks[0]
        content = first.text if isinstance(first, TextBlock) else ""
    elif blocks:
        content = blocks
    else:
        raw_content = data.get("content")
        content = raw_content if isinstance(raw_content, str) else ""
    return Message(role=role, content=content, tool_call_id=as_str(data.get("tool_call_id")))


def _tools(tools: JsonValue) -> list[dict[str, JsonValue]] | None:
    if not isinstance(tools, list):
        return None
    result: list[dict[str, JsonValue]] = []
    for tool in tools:
        data = as_dict(tool)
        function = as_dict(data.get("function")) or data
        name = as_str(function.get("name"))
        if name is None:
            continue
        entry: dict[str, JsonValue] = {"name": name}
        description = as_str(function.get("description"))
        if description is not None:
            entry["description"] = description
        parameters = function.get("parameters")
        if isinstance(parameters, dict):
            entry["parameters"] = parameters
        result.append(entry)
    return result


def _tool_choice(choice: JsonValue) -> JsonValue:
    if isinstance(choice, str):
        return choice if choice in ("auto", "none", "required") else None
    data = as_dict(choice)
    name = as_str(as_dict(data.get("function")).get("name")) or as_str(data.get("name"))
    return {"name": name} if name else None
