"""``LlmAdapter``: the one-way translation from a provider's shape to the canonical shape.

Design section 4.3. An adapter derives the canonical ``LlmInput`` and ``LlmOutput`` from the
**JSON form** of the raw input and output, which are stored unchanged alongside. There is no
``from_canonical``: replay hands back ``output.raw`` directly, so nothing has to be mapped back.

Contract for ``llm`` boundaries: the output must fill the fixed homes for cost data
(``provider``, ``model``, ``model_source`` and the exclusive, additive ``usage`` buckets), whatever
the SDK or agent framework. Each supported provider has a conformance test in ``tests/providers``.
"""

from typing import Protocol

from agentplane_primitives.models import LlmInput, LlmOutput
from pydantic import JsonValue


class LlmAdapter(Protocol):
    """Translates one provider's raw JSON into the canonical LLM input and output."""

    provider: str
    """The value written to ``output.provider``."""

    def to_canonical_input(self, raw: dict[str, JsonValue]) -> LlmInput:
        """Derive the canonical input from the arguments as passed, by name, as JSON."""
        ...

    def to_canonical_output(self, raw: JsonValue, requested_model: str | None) -> LlmOutput:
        """Derive the canonical output from the returned value as JSON.

        ``requested_model`` is the model the caller asked for; it is copied into the output with
        ``model_source = requested`` when the response does not name the served model.
        """
        ...
