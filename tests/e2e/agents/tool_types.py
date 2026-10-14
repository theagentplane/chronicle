"""``Tool``: a framework-neutral tool an agent can call (test double, not shipped)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

SYSTEM_PROMPT = "You are a helpful agent. Use tools when they help."


@dataclass(frozen=True)
class Tool:
    """A named async function with a JSON-schema parameter description."""

    name: str
    description: str
    run: Callable[..., Awaitable[str]]
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"task": {"type": "string"}},
            "required": ["task"],
        }
    )

    def openai_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def anthropic_definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }
