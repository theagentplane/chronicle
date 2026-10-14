"""Read and change the active session and envelope stack (design section 4.6)."""

from collections.abc import Iterator
from contextlib import contextmanager

from chronicle.framework.context.context_vars import (
    current_session_var,
    envelope_stack_var,
)
from chronicle.framework.context.recording_session import RecordingSession


def current_session() -> RecordingSession | None:
    """Return the active session without creating one."""
    return current_session_var.get()


@contextmanager
def use_session(session: RecordingSession) -> Iterator[RecordingSession]:
    """Make ``session`` the active session for the enclosed block (and start a fresh stack)."""
    session_token = current_session_var.set(session)
    stack_token = envelope_stack_var.set(())
    try:
        yield session
    finally:
        envelope_stack_var.reset(stack_token)
        current_session_var.reset(session_token)


def current_envelope_id() -> str | None:
    """Return the id of the innermost crossing in progress, if any."""
    stack = envelope_stack_var.get()
    return stack[-1] if stack else None
