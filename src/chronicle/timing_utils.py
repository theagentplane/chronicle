"""Time helper: one place that returns the current time as a time-zone aware UTC datetime."""

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return the current time in UTC (primitives requires time zones on all timestamps)."""
    return datetime.now(timezone.utc)
