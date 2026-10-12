"""Capability: record (design section 6)."""

from chronicle.capabilities.record.record_environment_types import RecordEnvironment
from chronicle.capabilities.record.recorder import (
    arecord_request,
    close_span,
    open_span,
    record_request,
    register_trace,
    start_request,
)
from chronicle.capabilities.record.registration_enums import TraceRegistration

__all__ = [
    "RecordEnvironment",
    "TraceRegistration",
    "arecord_request",
    "close_span",
    "open_span",
    "record_request",
    "register_trace",
    "start_request",
]
