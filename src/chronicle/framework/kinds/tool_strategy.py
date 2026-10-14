"""The ``tool`` strategy: the generic JSON path (design sections 2.3 and 4.2).

For a tool the canonical view is the raw data itself, so it is stored once: ``input.raw`` is the
bound arguments by name and ``output.raw`` is the JSON form of the return value.
"""

from typing import Any

from agentplane_primitives.enums import Kind
from agentplane_primitives.models import (
    Envelope,
    LlmInput,
    LlmOutput,
    OutputError,
    ToolInput,
    ToolOutput,
)
from pydantic import JsonValue

from chronicle.framework.boundary_spec_types import BoundarySpec
from chronicle.framework.kinds.kind_strategy_types import KindStrategy
from chronicle.framework.kinds.recorded_value_utils import to_recorded


class ToolStrategy(KindStrategy):
    """Behaviour of ``kind = tool``."""

    kind = Kind.TOOL

    def build_input(self, spec: BoundarySpec, raw: dict[str, JsonValue]) -> LlmInput | ToolInput:
        return ToolInput(raw=raw)

    def build_output(
        self, spec: BoundarySpec, raw_input: dict[str, JsonValue], raw_output: JsonValue
    ) -> LlmOutput | ToolOutput:
        return ToolOutput(raw=raw_output)

    def build_error(self, error: OutputError) -> LlmOutput | ToolOutput:
        return ToolOutput(error=error)

    def stub_value(self, envelope: Envelope) -> Any:
        output = envelope.output
        return to_recorded(output.raw if isinstance(output, ToolOutput) else None)
