"""``EnvelopeSink``: where a recording session hands finished records (design sections 4.6, 5.1).

The framework layer does no I/O. It writes spans and envelopes to a sink, and the repositories
layer provides the sink that queues them for the control plane. Writes are non-blocking
enqueues; ``flush`` blocks until what was enqueued has been delivered (or failed).
"""

from typing import Protocol

from agentplane_primitives.models import Envelope, Span


class EnvelopeSink(Protocol):
    """Receives the writes of one or more sessions."""

    def write_span(self, span: Span) -> None:
        """Upsert a span (open at the start, closed at the end)."""
        ...

    def write_envelope(self, envelope: Envelope) -> None:
        """Append an envelope (an open write when ``emit_open`` is on, then the close write)."""
        ...

    def flush(self) -> None:
        """Deliver everything enqueued so far. Raises in strict mode if a delivery failed."""
        ...
