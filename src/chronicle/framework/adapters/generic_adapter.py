"""The generic adapter: used when no provider adapter matches (design section 4.3).

A custom function wrapped with ``@boundary(kind="llm")`` and no adapter has an unknown return
shape. Its envelope carries ``usage = null`` and ``provider = unknown``; consumers must tolerate
null, or the developer supplies an adapter. The generic adapter reads only what is safe to read:
the model and messages when the arguments carry them in the common shape, and a plain string
result as one text block. ``raw`` always holds everything.
"""

from agentplane_primitives.enums import MessageRole
from agentplane_primitives.models import LlmInput, LlmOutput, Message, TextBlock
from agentplane_primitives.types import UNKNOWN_PROVIDER
from pydantic import JsonValue

from chronicle.framework.adapters.json_access_utils import as_dict, as_list, as_str
from chronicle.framework.adapters.llm_params_utils import params_from_arguments
from chronicle.framework.adapters.openai_adapter import UNKNOWN_MODEL

_ROLES = {role.value for role in MessageRole}


class GenericLlmAdapter:
    """Adapter for LLM boundaries with an unknown provider."""

    provider = UNKNOWN_PROVIDER

    def to_canonical_input(self, raw: dict[str, JsonValue]) -> LlmInput:
        messages: list[Message] = []
        for item in as_list(raw.get("messages")):
            data = as_dict(item)
            role = data.get("role")
            content = data.get("content")
            if isinstance(role, str) and role in _ROLES and isinstance(content, str):
                messages.append(Message(role=MessageRole(role), content=content))
        return LlmInput(
            model=as_str(raw.get("model")) or UNKNOWN_MODEL,
            messages=messages,
            params=params_from_arguments(raw),
            raw=raw,
        )

    def to_canonical_output(self, raw: JsonValue, requested_model: str | None) -> LlmOutput:
        content = [TextBlock(text=raw)] if isinstance(raw, str) and raw else []
        return LlmOutput(content=content, raw=raw)  # type: ignore[arg-type]
