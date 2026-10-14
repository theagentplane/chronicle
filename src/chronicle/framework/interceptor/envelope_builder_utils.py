"""Build the envelope records of a crossing (design sections 2.4 and 6.1).

Order of operations follows design section 12.1 (redaction order): convert to JSON, redact the
raw form, derive the canonical fields from the redacted raw, then store. So no secret that a
redactor masks can reappear in a canonical field.
"""

import logging
import re
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from agentplane_primitives.enums import State, Status
from agentplane_primitives.models import (
    Envelope,
    EnvelopeStatus,
    LlmInput,
    LlmOutput,
    OutputError,
    ToolInput,
    ToolOutput,
)
from pydantic import JsonValue

from chronicle.framework.interceptor.crossing_types import Crossing
from chronicle.framework.redaction.redaction_utils import redact_json
from chronicle.framework.serialization.json_utils import to_json
from chronicle.framework.serialization.truncation_utils import truncate_json
from chronicle.timing_utils import utc_now

_log = logging.getLogger("chronicle")
_METADATA_KEY = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)*$")
SEQUENCE_KEY = "chronicle.sequence"
INVOCATION_KEY = "chronicle.invocation_index"
TRUNCATED_KEY = "chronicle.truncated"


def prepare_input(crossing: Crossing) -> tuple[dict[str, JsonValue], LlmInput | ToolInput, bool]:
    """Return the redacted raw input, the canonical input and whether anything was truncated."""
    settings = crossing.session.settings
    raw: JsonValue = crossing.arguments if settings.capture_input else {}
    raw = redact_json(raw, settings.redactors)
    raw, truncated = truncate_json(raw, settings.max_payload_bytes)
    raw_dict = raw if isinstance(raw, dict) else {}
    return raw_dict, crossing.strategy.build_input(crossing.spec, raw_dict), truncated


def prepare_output(
    crossing: Crossing, raw_input: dict[str, JsonValue], result: Any
) -> tuple[LlmOutput | ToolOutput, Mapping[str, Any], bool]:
    """Return the canonical output (derived from redacted raw), extra metadata, truncation."""
    settings = crossing.session.settings
    spec = crossing.spec
    shaped = _shape_result(spec.name, spec.extract_result, result)
    raw: JsonValue = to_json(shaped) if settings.capture_output else None
    raw = redact_json(raw, settings.redactors)
    raw, truncated = truncate_json(raw, settings.max_payload_bytes)
    extra = _result_metadata(spec.name, spec.extract_metadata, result)
    return crossing.strategy.build_output(spec, raw_input, raw), extra, truncated


def _shape_result(name: str, extract: Callable[[Any], Any] | None, result: Any) -> Any:
    """Apply the developer's ``extract_result``; a failure there falls back to the real result."""
    if extract is None:
        return result
    try:
        return extract(result)
    except Exception:
        _log.warning("chronicle extract_result failed for %r", name, exc_info=True)
        return result


def _result_metadata(
    name: str, extract: Callable[[Any], Mapping[str, Any]] | None, result: Any
) -> Mapping[str, Any]:
    """Apply the developer's ``extract_metadata``; a failure there adds no metadata."""
    if extract is None:
        return {}
    try:
        return extract(result) or {}
    except Exception:
        _log.warning("chronicle extract_metadata failed for %r", name, exc_info=True)
        return {}


def error_output(crossing: Crossing, exc: BaseException) -> OutputError:
    """Describe a raised exception as ``output.error`` (the message is redacted)."""
    message = redact_json(str(exc), crossing.session.settings.redactors)
    return OutputError(type=type(exc).__name__, message=message if isinstance(message, str) else "")


def build_metadata(
    crossing: Crossing, extra: Mapping[str, Any] | None = None, truncated: bool = False
) -> dict[str, JsonValue]:
    """Static metadata, then the span-local counters, then what the call added."""
    metadata: dict[str, JsonValue] = dict(crossing.spec.metadata)
    for key, value in (extra or {}).items():
        if _METADATA_KEY.match(str(key)):
            metadata[str(key)] = to_json(value)
    metadata[SEQUENCE_KEY] = crossing.sequence
    metadata[INVOCATION_KEY] = crossing.invocation_index
    if truncated:
        metadata[TRUNCATED_KEY] = True
    return metadata


def build_open_envelope(
    crossing: Crossing, input_model: LlmInput | ToolInput, truncated: bool
) -> Envelope:
    """The open write: identity and input, no output yet (``emit_open``)."""
    return Envelope(
        envelope_id=crossing.envelope_id,
        span_id=crossing.session.span_id,
        trace_id=crossing.session.trace_id,
        parent_envelope_id=crossing.parent_envelope_id,
        name=crossing.spec.name,
        kind=crossing.spec.kind,
        attempt=crossing.attempt,
        links=crossing.links,
        envelope_status=EnvelopeStatus(state=State.OPEN, started_at=crossing.started_at),
        input=input_model,
        metadata=build_metadata(crossing, truncated=truncated),
    )


def build_closed_envelope(
    crossing: Crossing,
    input_model: LlmInput | ToolInput,
    output_model: LlmOutput | ToolOutput,
    status: Status,
    metadata: dict[str, JsonValue],
    ended_at: datetime | None = None,
) -> Envelope:
    """The close write: the same record with its output and result."""
    return Envelope(
        envelope_id=crossing.envelope_id,
        span_id=crossing.session.span_id,
        trace_id=crossing.session.trace_id,
        parent_envelope_id=crossing.parent_envelope_id,
        name=crossing.spec.name,
        kind=crossing.spec.kind,
        attempt=crossing.attempt,
        links=crossing.links,
        envelope_status=EnvelopeStatus(
            state=State.CLOSED,
            status=status,
            started_at=crossing.started_at,
            ended_at=ended_at or utc_now(),
        ),
        input=input_model,
        output=output_model,
        metadata=metadata,
    )
