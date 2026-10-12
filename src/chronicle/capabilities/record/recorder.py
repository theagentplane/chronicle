"""The record workflow for one request: entry, per-crossing, exit (design sections 3.3 and 6.1).

1. **Entry.** A valid inbound ``traceparent`` is joined: a new span opens with
   ``parent_envelope_id`` set from it. Otherwise a ``trace_id`` is minted, registered
   **synchronously** (idempotent; labels written once) and the first span opens.
2. **Per crossing** (inside the span): handled by the interceptor.
3. **Exit.** The span is closed (``failure`` if the request handler raised, otherwise
   ``success``) and the queue is flushed.

Trace registration failure policy (design 3.3): fail-open by default, so the request carries on
with the locally minted id and the control plane creates the trace on first ingest; strict mode
fails the request. Span registration is asynchronous: a span's existence is implied by its first
envelope.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

from agentplane_primitives.enums import State, Status
from agentplane_primitives.models import Span, Trace, TraceContext
from agentplane_primitives.utils import new_span_id, new_trace_id
from pydantic import JsonValue

from chronicle.capabilities.record.record_environment_types import RecordEnvironment
from chronicle.capabilities.record.registration_enums import TraceRegistration
from chronicle.framework.boundary_enums import SessionMode
from chronicle.framework.context.recording_session import RecordingSession
from chronicle.framework.context.session_context_utils import use_session
from chronicle.repositories.errors import ControlPlaneError, RegistrationError
from chronicle.timing_utils import utc_now

_log = logging.getLogger("chronicle")


def register_trace(env: RecordEnvironment, trace: Trace) -> None:
    """Register ``trace`` with the control plane, following the failure policy."""
    if (
        env.client is None
        or not env.settings.recording
        or env.trace_registration is TraceRegistration.LAZY
    ):
        return
    try:
        env.client.upsert_trace(trace)
    except ControlPlaneError as exc:
        if env.registration_fail_open:
            _log.warning("chronicle could not register trace %s: %s", trace.trace_id, exc)
            return
        raise RegistrationError(str(exc), status_code=exc.status_code) from exc


def new_trace(
    trace_id: str | None,
    name: str | None,
    labels: dict[str, str] | None,
) -> Trace:
    """Build the trace entity for a new root (labels are strings, written once)."""
    return Trace(
        trace_id=trace_id or new_trace_id(),
        name=name,
        metadata=dict(labels or {}),
        state=State.OPEN,
    )


def open_span(
    env: RecordEnvironment,
    *,
    trace_id: str,
    parent_envelope_id: str | None,
    service: str | None = None,
    metadata: dict[str, JsonValue] | None = None,
) -> RecordingSession:
    """Create the session for a new span and enqueue its open write."""
    session = RecordingSession(
        trace_id=trace_id,
        span_id=new_span_id(),
        service=service or env.service,
        mode=SessionMode.RECORD,
        parent_envelope_id=parent_envelope_id,
        sink=env.sink,
        settings=env.settings,
        hooks=env.hooks.copy(),
        metadata=metadata,
    )
    _write_span(env, session, closed=False, status=None)
    return session


def close_span(env: RecordEnvironment, session: RecordingSession, *, failed: bool) -> None:
    """Enqueue the close write of the span and flush the queue.

    Raises ``DeliveryError`` in strict mode if a queued write could not be delivered.
    """
    _write_span(env, session, closed=True, status=Status.FAILURE if failed else Status.SUCCESS)
    if env.sink is not None and env.settings.recording:
        env.sink.flush()


def _write_span(
    env: RecordEnvironment, session: RecordingSession, *, closed: bool, status: Status | None
) -> None:
    if env.sink is None or not env.settings.recording:
        return
    if closed:
        span = Span(
            span_id=session.span_id,
            trace_id=session.trace_id,
            parent_envelope_id=session.parent_envelope_id,
            service=session.service,
            state=State.CLOSED,
            status=status,
            started_at=session.started_at,
            ended_at=utc_now(),
            metadata=session.metadata,
        )
    else:
        span = Span(
            span_id=session.span_id,
            trace_id=session.trace_id,
            parent_envelope_id=session.parent_envelope_id,
            service=session.service,
            state=State.OPEN,
            started_at=session.started_at,
            metadata=session.metadata,
        )
    try:
        env.sink.write_span(span)
    except Exception:
        _log.warning("chronicle could not enqueue a span", exc_info=True)


def start_request(
    env: RecordEnvironment,
    *,
    context: TraceContext | None,
    trace_id: str | None = None,
    trace_name: str | None = None,
    trace_labels: dict[str, str] | None = None,
    service: str | None = None,
    metadata: dict[str, JsonValue] | None = None,
) -> RecordingSession:
    """Entry: join the inbound trace, or mint and register a new one, then open the span."""
    if context is not None:
        return open_span(
            env,
            trace_id=context.trace_id,
            parent_envelope_id=context.parent_envelope_id,
            service=service,
            metadata=metadata,
        )
    trace = new_trace(trace_id, trace_name, trace_labels)
    register_trace(env, trace)
    return open_span(
        env, trace_id=trace.trace_id, parent_envelope_id=None, service=service, metadata=metadata
    )


@contextmanager
def record_request(
    env: RecordEnvironment,
    *,
    context: TraceContext | None = None,
    trace_id: str | None = None,
    trace_name: str | None = None,
    trace_labels: dict[str, str] | None = None,
    service: str | None = None,
    metadata: dict[str, JsonValue] | None = None,
) -> Iterator[RecordingSession]:
    """Record one request: open the span, make it active, close and flush on exit."""
    session = start_request(
        env,
        context=context,
        trace_id=trace_id,
        trace_name=trace_name,
        trace_labels=trace_labels,
        service=service,
        metadata=metadata,
    )
    failed = False
    try:
        with use_session(session):
            yield session
    except BaseException:
        failed = True
        raise
    finally:
        close_span(env, session, failed=failed)


@asynccontextmanager
async def arecord_request(
    env: RecordEnvironment,
    *,
    context: TraceContext | None = None,
    trace_id: str | None = None,
    trace_name: str | None = None,
    trace_labels: dict[str, str] | None = None,
    service: str | None = None,
    metadata: dict[str, JsonValue] | None = None,
) -> AsyncIterator[RecordingSession]:
    """Async form of ``record_request``: the blocking registration and flush run in a thread."""
    session = await asyncio.to_thread(
        start_request,
        env,
        context=context,
        trace_id=trace_id,
        trace_name=trace_name,
        trace_labels=trace_labels,
        service=service,
        metadata=metadata,
    )
    failed = False
    try:
        with use_session(session):
            yield session
    except BaseException:
        failed = True
        raise
    finally:
        await asyncio.to_thread(close_span, env, session, failed=failed)
