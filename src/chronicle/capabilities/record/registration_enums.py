"""Closed set for trace registration (design section 3.3)."""

from agentplane_primitives.enums import BaseEnum


class TraceRegistration(BaseEnum):
    """When a new trace is registered with the control plane."""

    SYNC = "sync"
    LAZY = "lazy"
