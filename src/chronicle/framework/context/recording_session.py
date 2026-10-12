"""``RecordingSession``: the in-memory object that records one span (design section 4.6).

One recording session per span. A trace can have many spans, in one process or several, each
with its own session. The session holds the trace context, the hooks, the settings, the sink the
finished records go to, the span-local counters and, in REPLAY, the replay control.

**Counters** (both span-local, so there is no distributed ordering problem):

- ``sequence``: start order of envelopes in the span.
- ``invocation_index``: "this is the n-th call of boundary X in this span". Replay uses it to
  match a recording.

The active envelope stack is context-scoped (see ``context_vars``), not held here, so concurrent
async requests and threads nest independently even when they share a session.
"""

import threading
from datetime import datetime

from pydantic import JsonValue

from chronicle.framework.boundary_enums import SessionMode
from chronicle.framework.context.envelope_sink_types import EnvelopeSink
from chronicle.framework.context.replay_control_types import ReplayControl
from chronicle.framework.context.session_settings_types import SessionSettings
from chronicle.framework.hooks.hook_registry import HookRegistry
from chronicle.timing_utils import utc_now


class RecordingSession:
    """Records one span, or serves it from a recording."""

    def __init__(
        self,
        *,
        trace_id: str,
        span_id: str,
        service: str,
        mode: SessionMode = SessionMode.RECORD,
        parent_envelope_id: str | None = None,
        sink: EnvelopeSink | None = None,
        settings: SessionSettings | None = None,
        hooks: HookRegistry | None = None,
        replay: ReplayControl | None = None,
        started_at: datetime | None = None,
        metadata: dict[str, JsonValue] | None = None,
    ) -> None:
        self.trace_id = trace_id
        self.span_id = span_id
        self.service = service
        self.mode = mode
        self.parent_envelope_id = parent_envelope_id
        self.sink = sink
        self.settings = settings or SessionSettings()
        self.hooks = hooks if hooks is not None else HookRegistry()
        self.replay = replay
        self.started_at = started_at or utc_now()
        self.metadata: dict[str, JsonValue] = dict(metadata or {})
        self._lock = threading.Lock()
        self._sequence = 0
        self._invocations: dict[str, int] = {}

    def next_sequence(self) -> int:
        """Return the next span-local sequence number (1 for the first envelope)."""
        with self._lock:
            self._sequence += 1
            return self._sequence

    def next_invocation(self, name: str) -> int:
        """Return how many times ``name`` has now been called in this span (1 for the first)."""
        with self._lock:
            count = self._invocations.get(name, 0) + 1
            self._invocations[name] = count
            return count

    @property
    def is_replay(self) -> bool:
        """True when the session serves a recording instead of capturing."""
        return self.mode is SessionMode.REPLAY
