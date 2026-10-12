"""``ControlPlaneClient``: the contract Chronicle needs from the control plane (design 5).

Chronicle has one backend, the control plane over HTTP, and needs exactly three writes and one
read. Whole-trace reads, envelope lookups and trace listing are control-plane concerns and are
not part of this contract. The control-plane HTTP API is not final (design 10.2): code against
this interface so that, if the endpoints change, only the client changes.
"""

from collections.abc import Sequence
from typing import Protocol

from agentplane_primitives.models import Envelope, Span, Trace


class ControlPlaneClient(Protocol):
    """What Chronicle asks of the control plane."""

    def upsert_trace(self, trace: Trace) -> None:
        """Register a trace: idempotent, client-supplied id, labels written once."""
        ...

    def upsert_span(self, span: Span) -> None:
        """Create or update a span (open at the start, closed at the end)."""
        ...

    def append_envelopes(self, envelopes: Sequence[Envelope]) -> None:
        """Append envelopes (an open record is updated when its close arrives)."""
        ...

    def read_span_envelopes(self, trace_id: str, span_id: str) -> list[Envelope]:
        """Return the envelopes of span ``span_id`` in trace ``trace_id`` (for replay)."""
        ...

    def close(self) -> None:
        """Release any resources held by the client."""
        ...
