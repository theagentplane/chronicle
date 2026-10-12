"""The replay workflow: serve one span's recording to the boundaries (design sections 5.2, 7.1).

Replay is scoped to a service request instance: ``trace_id`` plus ``span_id``. The envelopes of
that span are read from the control plane by those ids. A span's outbound calls to other services
are tool envelopes, so on replay they are stubbed with the recorded response and the downstream
span is not re-run; it can be replayed on its own.

Nothing is written during replay. ``RUN`` boundaries execute real code; ``STUB`` boundaries hand
back ``output.raw``.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from agentplane_primitives.models import Envelope
from agentplane_primitives.utils import new_span_id

from chronicle.capabilities.replay.replay_plan_types import ReplayPlan
from chronicle.capabilities.replay.replay_state import ReplayState
from chronicle.framework.boundary_enums import SessionMode
from chronicle.framework.context.recording_session import RecordingSession
from chronicle.framework.context.session_context_utils import use_session
from chronicle.framework.context.session_settings_types import SessionSettings
from chronicle.framework.hooks.hook_registry import HookRegistry
from chronicle.repositories.repository_types import ControlPlaneClient


@dataclass(frozen=True)
class ReplayRun:
    """The handle a replay block yields: assert on it after the agent has run."""

    session: RecordingSession
    state: ReplayState

    @property
    def trace_id(self) -> str:
        return self.session.trace_id

    def captured_input(self, name: str, invocation_index: int) -> object:
        """The arguments the ``RUN`` call of ``name`` received."""
        return self.state.captured_input(name, invocation_index)

    def captured_result(self, name: str, invocation_index: int) -> object:
        """What the ``RUN`` call of ``name`` returned."""
        return self.state.captured_result(name, invocation_index)

    def invocation_count(self, name: str) -> int:
        return self.state.invocation_count(name)

    def call_log(self) -> list[object]:
        return list(self.state.call_log())


def load_recording(client: ControlPlaneClient, trace_id: str, span_id: str) -> list[Envelope]:
    """Read the envelopes of span ``span_id`` in trace ``trace_id`` from the control plane."""
    return client.read_span_envelopes(trace_id, span_id)


@contextmanager
def replay_envelopes(
    envelopes: list[Envelope],
    plan: ReplayPlan | None = None,
    *,
    trace_id: str,
    hooks: HookRegistry | None = None,
) -> Iterator[ReplayRun]:
    """Replay the given recorded envelopes: boundaries inside the block are served from them."""
    state = ReplayState(envelopes, plan)
    session = RecordingSession(
        trace_id=trace_id,
        span_id=new_span_id(),
        service="replay",
        mode=SessionMode.REPLAY,
        sink=None,
        settings=SessionSettings(recording=False),
        hooks=hooks.copy() if hooks is not None else HookRegistry(),
        replay=state,
    )
    with use_session(session):
        yield ReplayRun(session=session, state=state)
