"""``BoundarySpec``: everything the interceptor needs to know about one declared boundary.

Design sections 4.1 and 4.2. It is built once, when a boundary is declared (``@boundary``,
``wrap``, ``wrap_llm`` or an instrumenter), so per-call work is small and a bad declaration (an
unknown kind) fails at declaration time.
"""

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from agentplane_primitives.enums import Kind
from pydantic import JsonValue

from chronicle.framework.adapters.adapter_types import LlmAdapter


@dataclass(frozen=True)
class BoundarySpec:
    """A declared boundary: a name, a closed kind, and how to read its calls."""

    name: str
    kind: Kind
    adapter: LlmAdapter | None = None
    """For ``llm`` boundaries: the adapter that derives the canonical fields."""
    extract_input: Callable[..., Mapping[str, Any]] | None = None
    """Overrides the default signature-bound capture; returns the arguments by name."""
    extract_result: Callable[[Any], Any] | None = None
    """Shapes what is recorded as ``output.raw``; the caller still receives the real result."""
    extract_metadata: Callable[[Any], Mapping[str, Any]] | None = None
    """Adds envelope metadata derived from the result."""
    metadata: dict[str, JsonValue] = field(default_factory=dict)
    """Static envelope metadata, constant in code (for example ``client.library``)."""
    signature: inspect.Signature | None = None
    """The wrapped callable's signature, resolved once; ``None`` if it cannot be introspected."""
    requested_model_key: str = "model"
    """The argument that names the model the caller asked for (``llm`` boundaries)."""
