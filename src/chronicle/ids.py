"""OpenTelemetry-format identifiers.

A trace id is 16 bytes and a span id is 8 bytes, both rendered as lowercase hex
(32 and 16 characters), and neither may be all zeros. Chronicle uses these
formats directly: ``Envelope.trace_id`` is the OTel trace id and
``Envelope.envelope_id`` is the OTel span id, so an envelope can be exported to
any OTel platform without translating ids.
"""

from __future__ import annotations

import re
import secrets

TRACE_ID_HEX_LEN = 32
SPAN_ID_HEX_LEN = 16

_TRACE_ID_RE = re.compile(r"[0-9a-f]{32}")
_SPAN_ID_RE = re.compile(r"[0-9a-f]{16}")


def new_trace_id() -> str:
    """Random 16-byte trace id as 32 lowercase hex characters."""
    while True:
        value = secrets.token_hex(16)
        if int(value, 16):
            return value


def new_span_id() -> str:
    """Random 8-byte span id as 16 lowercase hex characters."""
    while True:
        value = secrets.token_hex(8)
        if int(value, 16):
            return value


def is_trace_id(value: object) -> bool:
    return isinstance(value, str) and bool(_TRACE_ID_RE.fullmatch(value)) and int(value, 16) != 0


def is_span_id(value: object) -> bool:
    return isinstance(value, str) and bool(_SPAN_ID_RE.fullmatch(value)) and int(value, 16) != 0


def validate_trace_id(value: str) -> str:
    if not is_trace_id(value):
        raise ValueError(
            f"invalid trace_id {value!r}: must be 32 lowercase hex characters "
            "(an OpenTelemetry trace id), not all zeros. Pass a human label as "
            "record(name=...) instead."
        )
    return value


def validate_span_id(value: str) -> str:
    if not is_span_id(value):
        raise ValueError(
            f"invalid span/envelope id {value!r}: must be 16 lowercase hex characters "
            "(an OpenTelemetry span id), not all zeros."
        )
    return value
