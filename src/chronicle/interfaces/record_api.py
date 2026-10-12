"""``record``, ``span``, ``replay_trace`` and ``replay``: the entry points (design 6.1, 7, 8.1).

``span`` is the custom API for any entry point that is not ASGI (CLI jobs, queue workers): it
opens a span for one request, joining the trace of ``parent`` if given, minting and registering a
new trace otherwise. ``record`` is the same thing with a trace name and labels, for the root of a
trace. Both close the span on exit (``failure`` if the block raised) and flush the queue.

``replay_trace`` reads the envelopes of span ``span_id`` in trace ``trace_id`` from the control
plane and serves them to the boundaries inside the block.
"""

from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager

from agentplane_primitives.models import Envelope, TraceContext
from pydantic import JsonValue

from chronicle.capabilities.record.recorder import arecord_request, record_request
from chronicle.capabilities.replay.replay_plan_types import ReplayPlan
from chronicle.capabilities.replay.replayer import (
    ReplayRun,
    load_recording,
    replay_envelopes,
)
from chronicle.framework.context.recording_session import RecordingSession
from chronicle.framework.hooks.hook_registry import default_hooks
from chronicle.interfaces.propagation_api import coerce_parent
from chronicle.interfaces.runtime_utils import get_client, get_environment, get_settings
from chronicle.repositories.errors import ControlPlaneError
from chronicle.repositories.repository_types import ControlPlaneClient


@contextmanager
def span(
    parent: TraceContext | Mapping[str, str] | None = None,
    *,
    service: str | None = None,
    metadata: dict[str, JsonValue] | None = None,
) -> Iterator[RecordingSession]:
    """Open a span for one request. ``parent`` is a ``TraceContext`` or inbound headers."""
    context = coerce_parent(parent)
    with record_request(
        get_environment(), context=context, service=service, metadata=metadata
    ) as session:
        yield session


@asynccontextmanager
async def aspan(
    parent: TraceContext | Mapping[str, str] | None = None,
    *,
    service: str | None = None,
    metadata: dict[str, JsonValue] | None = None,
) -> AsyncIterator[RecordingSession]:
    """Async form of ``span``: registration and flush run in a worker thread."""
    context = coerce_parent(parent)
    async with arecord_request(
        get_environment(), context=context, service=service, metadata=metadata
    ) as session:
        yield session


@contextmanager
def record(
    name: str | None = None,
    *,
    trace_id: str | None = None,
    labels: dict[str, str] | None = None,
    service: str | None = None,
    metadata: dict[str, JsonValue] | None = None,
) -> Iterator[RecordingSession]:
    """Record one request as the root of a new trace.

        with chronicle.record("checkout", labels={"session_id": "s1", "user_id": "u1"}) as s:
            run_agent(...)

    ``name`` is a human label; ``labels`` are the trace's labels (string values, written once);
    ``trace_id`` is minted unless given (32 lowercase hex characters).
    """
    with record_request(
        get_environment(),
        trace_id=trace_id,
        trace_name=name,
        trace_labels=labels,
        service=service,
        metadata=metadata,
    ) as session:
        yield session


@contextmanager
def replay_trace(
    trace_id: str,
    span_id: str,
    plan: ReplayPlan | None = None,
    *,
    client: ControlPlaneClient | None = None,
) -> Iterator[ReplayRun]:
    """Replay span ``span_id`` of trace ``trace_id``, read from the control plane.

    with chronicle.replay_trace(trace_id, span_id, ReplayPlan().run("delete_file")) as run:
        run_agent(...)
        assert run.captured_result("delete_file", 1)["blocked"] is True
    """
    source = client or get_client()
    if source is None:
        raise ControlPlaneError(
            "replay needs a control plane: set control_plane_url (or CHRONICLE_CONTROL_PLANE_URL)"
        )
    envelopes = load_recording(source, trace_id, span_id)
    with replay_envelopes(envelopes, plan, trace_id=trace_id, hooks=default_hooks) as run:
        yield run


@contextmanager
def replay(
    envelopes: list[Envelope],
    plan: ReplayPlan | None = None,
    *,
    trace_id: str | None = None,
) -> Iterator[ReplayRun]:
    """Replay envelopes you already hold (for example read with your own client)."""
    resolved = trace_id or (envelopes[0].trace_id if envelopes else get_settings().service_name)
    with replay_envelopes(envelopes, plan, trace_id=resolved, hooks=default_hooks) as run:
        yield run
