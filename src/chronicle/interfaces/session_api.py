"""``current_session``: read the active span's session (design sections 4.6 and 8, ADR 0010).

A read-only view for code that needs to know which span it is running in, for example to take its
``trace_id``, ``span_id`` and ``parent_envelope_id``. It delegates to the framework; nothing here
opens, starts or changes a span.
"""

from chronicle.framework.context.recording_session import RecordingSession
from chronicle.framework.context.session_context_utils import current_session as _current_session


def current_session() -> RecordingSession | None:
    """Return the session of the span that is active in this context, or ``None``.

    The session carries ``trace_id``, ``span_id`` and ``parent_envelope_id`` (``None`` for a root
    span). It is set by ``chronicle.span``, ``chronicle.aspan``, ``chronicle.record`` and a
    ``ChronicleMiddleware`` request. It is held in a ``contextvars.ContextVar``, so it is isolated
    per asyncio task and is inherited by tasks created inside the span; a plain thread does not
    inherit it unless the context is copied into it.

    Returns ``None`` when no span is active. It never creates or starts a span. Note that a
    boundary called outside any span is still recorded, on an implicit ambient session that
    Chronicle opens on demand; that session is not returned here, so ``None`` means "not inside
    an explicit span", not "nothing is being recorded".
    """
    return _current_session()
