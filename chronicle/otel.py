"""First-class OpenTelemetry export: one span per boundary crossing.

Chronicle records each boundary crossing as an Envelope. ``instrument_otel`` turns each
recorded Envelope into an OpenTelemetry span using OpenInference semantic conventions, so
recorded runs land in Phoenix (or any OTel backend) with the right shape: LLM and tool
spans carrying input/output, model, and token counts, nested by the run's call graph.

    with chronicle.record("run-1") as session:
        chronicle.instrument_otel()      # emit spans for this run (uses the active session)
        run_agent(...)

Call it inside the ``record`` block (so it attaches to the recording session), or pass
``session=`` explicitly. Requires the OpenTelemetry SDK and OpenInference conventions:
``pip install agent-chronicle[phoenix]``. Nothing here is imported by ``import chronicle``,
so the base install needs neither package.

Spans start when the Chronicle nest stack opens (``start_span``), so children can parent
to an already-active OTel span — matching OTel Context semantics even though the
Envelope is written after the boundary body returns.
"""

from __future__ import annotations

import functools
import json
import threading
from datetime import datetime
from typing import Any, Callable

from chronicle.envelope.schema import Envelope
from chronicle.session import ChronicleSession, get_session


def _require_trace():
    try:
        from opentelemetry import trace

        return trace
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ImportError(
            "OpenTelemetry export needs the OTel SDK and OpenInference conventions: "
            "pip install agent-chronicle[phoenix]"
        ) from exc


def _span_kind(kind: str) -> str:
    from openinference.semconv.trace import OpenInferenceSpanKindValues as Kind

    return {"llm": Kind.LLM.value, "tool": Kind.TOOL.value}.get(kind, Kind.CHAIN.value)


def _input_value(envelope: Envelope) -> Any:
    state = envelope.input
    return [m.model_dump() for m in state.messages] or state.arguments or {}


def _output_value(envelope: Envelope) -> Any:
    output = envelope.output
    if envelope.status.code == "ERROR":
        return {"error": envelope.status.message, "error_type": envelope.attributes.get("error.type")}
    llm = output.llm
    if llm is not None:
        if llm.tool_calls:
            return [tc.model_dump() for tc in llm.tool_calls]
        if llm.text is not None:
            return llm.text
    if output.value is not None:
        return output.value
    return {}


def _as_json(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return str(value)


def envelope_span_attributes(envelope: Envelope) -> dict[str, Any]:
    """Map one Envelope to OpenInference span attributes."""
    from openinference.semconv.trace import SpanAttributes as S

    attributes: dict[str, Any] = {
        S.OPENINFERENCE_SPAN_KIND: _span_kind(envelope.kind),
        S.INPUT_VALUE: _as_json(_input_value(envelope)),
        S.OUTPUT_VALUE: _as_json(_output_value(envelope)),
        "chronicle.invocation_index": envelope.invocation_index,
    }
    if envelope.kind == "llm":
        if envelope.model:
            attributes[S.LLM_MODEL_NAME] = envelope.model
        usage = envelope.output.llm.usage if envelope.output.llm else None
        if usage is not None and usage.input_tokens is not None:
            attributes[S.LLM_TOKEN_COUNT_PROMPT] = usage.input_tokens
        if usage is not None and usage.output_tokens is not None:
            attributes[S.LLM_TOKEN_COUNT_COMPLETION] = usage.output_tokens
    if envelope.kind == "tool":
        attributes[S.TOOL_NAME] = envelope.name
    for key, value in (envelope.attributes or {}).items():
        attributes[key] = value
    return attributes


def _to_ns(moment: datetime | None) -> int | None:
    return None if moment is None else int(moment.timestamp() * 1_000_000_000)


@functools.lru_cache(maxsize=1)
def _preset_ids_class() -> type:
    """One-shot OTel IdGenerator handing back Chronicle's already-OTel-format ids."""
    from opentelemetry.sdk.trace.id_generator import IdGenerator

    class PresetIds(IdGenerator):
        def __init__(self, trace_id: str, span_id: str) -> None:
            self._trace_id = int(trace_id, 16)
            self._span_id = int(span_id, 16)

        def generate_trace_id(self) -> int:
            return self._trace_id

        def generate_span_id(self) -> int:
            return self._span_id

    return PresetIds


_id_swap_lock = threading.Lock()


def _start_with_ids(
    tracer: Any,
    name: str,
    context: Any,
    trace_id: str,
    span_id: str,
    start_time: datetime | None,
) -> Any:
    """Start an OTel span whose ids are the envelope's, not freshly generated ones.

    The SDK only takes ids from the tracer's ``id_generator``, so that is swapped for a
    one-shot generator around ``start_span``. A tracer without an ``id_generator``
    (a non-SDK tracer) keeps its own ids; the span is still emitted and nested.
    """
    kwargs = {"context": context, "start_time": _to_ns(start_time)}
    if not hasattr(tracer, "id_generator"):
        return tracer.start_span(name, **kwargs)
    with _id_swap_lock:
        original = tracer.id_generator
        tracer.id_generator = _preset_ids_class()(trace_id, span_id)
        try:
            return tracer.start_span(name, **kwargs)
        finally:
            tracer.id_generator = original


def instrument_otel(
    tracer: Any | None = None,
    *,
    session: ChronicleSession | None = None,
) -> Callable[[], None]:
    """Emit one OpenTelemetry span per recorded boundary crossing.

    Spans open on ``session.start_span`` (so nested work parents correctly) and close
    on ``on_record`` once envelope attributes are known. Returns a callable that
    removes the instrumentation.
    """
    trace = _require_trace()
    tracer = tracer or trace.get_tracer("chronicle")
    active = session or get_session()
    spans: dict[str, Any] = {}  # envelope_id -> live OTel span
    original_start = active.start_span
    original_end = active.end_span
    previous_on_record = active.on_record

    def start_span() -> tuple[str, str | None]:
        span_id, parent_id = original_start()
        parent = spans.get(parent_id) if parent_id else None
        context = trace.set_span_in_context(parent) if parent is not None else None
        # The OTel span reuses Chronicle's ids (trace_id / envelope_id are already in
        # OTel byte format). Name is finalized in on_record once the boundary id is known.
        spans[span_id] = _start_with_ids(
            tracer, "chronicle.boundary", context, active.trace_id, span_id,
            active._span_started_at.get(span_id),
        )
        return span_id, parent_id

    def end_span() -> None:
        original_end()

    def on_record(envelope: Envelope) -> None:
        span = spans.get(envelope.envelope_id)
        if span is None:
            # Caller recorded without start_span (legacy path): create + end now.
            parent = spans.get(envelope.parent_envelope_id) if envelope.parent_envelope_id else None
            context = trace.set_span_in_context(parent) if parent is not None else None
            span = _start_with_ids(
                tracer, envelope.name, context, envelope.trace_id, envelope.span_id,
                envelope.start_time or envelope.end_time,
            )
            spans[envelope.envelope_id] = span
        else:
            span.update_name(envelope.name)
        for key, value in envelope_span_attributes(envelope).items():
            span.set_attribute(key, value)
        if envelope.status.code == "ERROR":
            span.set_status(trace.Status(trace.StatusCode.ERROR, envelope.status.message))
        elif envelope.status.code == "OK":
            span.set_status(trace.Status(trace.StatusCode.OK))
        span.end(end_time=_to_ns(envelope.end_time))
        if previous_on_record is not None:
            previous_on_record(envelope)

    active.start_span = start_span  # type: ignore[method-assign]
    active.end_span = end_span  # type: ignore[method-assign]
    active.on_record = on_record

    def uninstrument() -> None:
        if active.start_span is start_span:
            active.start_span = original_start  # type: ignore[method-assign]
        if active.end_span is end_span:
            active.end_span = original_end  # type: ignore[method-assign]
        if active.on_record is on_record:
            active.on_record = previous_on_record

    return uninstrument
