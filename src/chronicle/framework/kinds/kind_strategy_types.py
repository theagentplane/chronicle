"""``KindStrategy``: the behaviour of one ``Kind`` member (design section 4.2).

Behaviour per kind lives in one strategy per enum member instead of ``if`` chains: how to capture
the input, how to build the output (and the output of a failed call), and how to build the value a
stub hands back. Adding a kind means adding it to the primitives enum and adding its strategy.
"""

from abc import ABC, abstractmethod
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


class KindStrategy(ABC):
    """What the interceptor asks of a kind. Inputs are the JSON forms, already redacted."""

    kind: Kind

    @abstractmethod
    def build_input(self, spec: BoundarySpec, raw: dict[str, JsonValue]) -> LlmInput | ToolInput:
        """Return the envelope input for the arguments ``raw`` (by name, as JSON)."""

    @abstractmethod
    def build_output(
        self, spec: BoundarySpec, raw_input: dict[str, JsonValue], raw_output: JsonValue
    ) -> LlmOutput | ToolOutput:
        """Return the envelope output for a call that returned ``raw_output`` (as JSON)."""

    @abstractmethod
    def build_error(self, error: OutputError) -> LlmOutput | ToolOutput:
        """Return the output of a failed call: it carries only the error."""

    @abstractmethod
    def stub_value(self, envelope: Envelope) -> Any:
        """Return what a stubbed boundary hands back for this recorded envelope."""
