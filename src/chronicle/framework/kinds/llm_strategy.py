"""The ``llm`` strategy: delegates shape translation to an adapter (design sections 4.2, 4.3).

The strategy owns the workflow; the adapter derives the canonical fields. It requires an adapter:
a boundary with no match gets the generic adapter, which records ``usage = null`` and
``provider = unknown``. The requested model is passed to the adapter so it can be copied into the
output (``model_source = requested``) when the response does not name the served model.
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

from chronicle.framework.adapters.adapter_registry import get_adapter
from chronicle.framework.adapters.adapter_types import LlmAdapter
from chronicle.framework.boundary_spec_types import BoundarySpec
from chronicle.framework.kinds.kind_strategy_types import KindStrategy
from chronicle.framework.kinds.recorded_value_utils import to_recorded


def _adapter_for(spec: BoundarySpec) -> LlmAdapter:
    return spec.adapter if spec.adapter is not None else get_adapter(None)


class LlmStrategy(KindStrategy):
    """Behaviour of ``kind = llm``."""

    kind = Kind.LLM

    def build_input(self, spec: BoundarySpec, raw: dict[str, JsonValue]) -> LlmInput | ToolInput:
        return _adapter_for(spec).to_canonical_input(raw)

    def build_output(
        self, spec: BoundarySpec, raw_input: dict[str, JsonValue], raw_output: JsonValue
    ) -> LlmOutput | ToolOutput:
        requested = raw_input.get(spec.requested_model_key)
        return _adapter_for(spec).to_canonical_output(
            raw_output, requested if isinstance(requested, str) and requested else None
        )

    def build_error(self, error: OutputError) -> LlmOutput | ToolOutput:
        return LlmOutput(error=error)

    def stub_value(self, envelope: Envelope) -> Any:
        output = envelope.output
        return to_recorded(output.raw if isinstance(output, LlmOutput) else None)
