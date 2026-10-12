"""Closed sets of the delivery policy (design section 2.9, config enums)."""

from agentplane_primitives.enums import BaseEnum


class OverflowPolicy(BaseEnum):
    """What ``append`` does when the delivery queue is full."""

    DROP = "drop"
    BLOCK = "block"
