"""The context variables that scope Chronicle state (design section 4.6).

Context variables, not plain globals: concurrent async requests and threads each see their own
active session and envelope stack, so their spans never interleave. All three are immutable
values replaced on change, never mutated in place.
"""

from contextvars import ContextVar

from chronicle.framework.context.recording_session import RecordingSession

current_session_var: ContextVar[RecordingSession | None] = ContextVar(
    "chronicle_session", default=None
)
"""The recording session of the request being handled, if any."""

envelope_stack_var: ContextVar[tuple[str, ...]] = ContextVar("chronicle_envelope_stack", default=())
"""Envelope ids of the crossings currently in progress, outermost first."""

attempt_var: ContextVar[tuple[int, str | None] | None] = ContextVar(
    "chronicle_attempt", default=None
)
"""The ``(attempt, retry_of)`` declared by ``attempt(...)``, if any."""
