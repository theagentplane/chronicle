"""An in-memory fake of the control-plane client (design section 5.4, test strategy).

It lives in the test suite and is not shipped as a backend. The wire format is covered by the
primitives models themselves, which Chronicle and the control plane both import: every record
handed to the fake has already been validated by them.
"""

import threading
from collections.abc import Sequence

from agentplane_primitives.models import Envelope, Span, Trace

from chronicle.repositories.errors import ControlPlaneError


def _sequence(envelope: Envelope) -> int:
    value = envelope.metadata.get("chronicle.sequence", 0)
    return value if isinstance(value, int) else 0


def invocation_index(envelope: Envelope) -> int:
    """The span-local call number Chronicle wrote into the envelope's metadata."""
    value = envelope.metadata.get("chronicle.invocation_index", 0)
    return value if isinstance(value, int) else 0


class InMemoryControlPlane:
    """Stores what Chronicle writes and serves a span's envelopes back."""

    def __init__(self) -> None:
        self.traces: dict[str, Trace] = {}
        self.spans: dict[tuple[str, str], Span] = {}
        self.envelopes: dict[tuple[str, str], Envelope] = {}
        self.order: list[str] = []
        self.fail_with: ControlPlaneError | None = None
        self._lock = threading.Lock()

    def upsert_trace(self, trace: Trace) -> None:
        self._maybe_fail()
        with self._lock:
            self.traces.setdefault(trace.trace_id, trace)
            self.order.append(f"trace:{trace.trace_id}")

    def upsert_span(self, span: Span) -> None:
        self._maybe_fail()
        with self._lock:
            self.spans[(span.trace_id, span.span_id)] = span
            self.order.append(f"span:{span.state.value}:{span.span_id}")

    def append_envelopes(self, envelopes: Sequence[Envelope]) -> None:
        self._maybe_fail()
        with self._lock:
            for envelope in envelopes:
                self.envelopes[(envelope.trace_id, envelope.envelope_id)] = envelope
                self.order.append(f"envelope:{envelope.name}")

    def read_span_envelopes(self, trace_id: str, span_id: str) -> list[Envelope]:
        with self._lock:
            return [
                e for (t, _), e in self.envelopes.items() if t == trace_id and e.span_id == span_id
            ]

    def close(self) -> None:
        return None

    # ---- helpers for assertions --------------------------------------------------------

    def all_envelopes(self) -> list[Envelope]:
        with self._lock:
            return sorted(self.envelopes.values(), key=_sequence)

    def envelopes_named(self, name: str) -> list[Envelope]:
        return [e for e in self.all_envelopes() if e.name == name]

    def _maybe_fail(self) -> None:
        if self.fail_with is not None:
            raise self.fail_with
