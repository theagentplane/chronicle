"""Closed sets used by the framework: session mode, boundary mode in replay, hook event.

Design sections 1.2 and 2.9. Each is a closed set: a new member is a design change.
"""

from agentplane_primitives.enums import BaseEnum


class SessionMode(BaseEnum):
    """What a recording session does: capture a request, or serve it from a recording."""

    RECORD = "record"
    REPLAY = "replay"


class BoundaryMode(BaseEnum):
    """What a boundary does in a REPLAY session: return the recording, or run real code."""

    STUB = "stub"
    RUN = "run"


class HookEvent(BaseEnum):
    """When a hook runs around a crossing (design section 4.4)."""

    ENTER = "enter"
    LEAVE = "leave"
    CROSSING = "crossing"
    RECORD = "record"
