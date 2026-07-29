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
"""

from __future__ import annotations

import json
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


def _span_kind(boundary_kind: str) -> str:
    from openinference.semconv.trace import OpenInferenceSpanKindValues as Kind

    return {"llm": Kind.LLM.value, "tool": Kind.TOOL.value}.get(boundary_kind, Kind.CHAIN.value)


def _input_value(envelope: Envelope) -> Any:
    state = envelope.input_state
    return state.messages or state.graph_state or {}


def _output_value(envelope: Envelope) -> Any:
    action = envelope.action_result
    if action.error:
        return {"error": action.error, "error_type": action.error_type}
    if action.tool_calls:
        return [tc.model_dump() if hasattr(tc, "model_dump") else tc for tc in action.tool_calls]
    if action.completion is not None:
        return action.completion
    if action.raw_response is not None:
        return action.raw_response
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
        S.OPENINFERENCE_SPAN_KIND: _span_kind(envelope.boundary_kind),
        S.INPUT_VALUE: _as_json(_input_value(envelope)),
        S.OUTPUT_VALUE: _as_json(_output_value(envelope)),
        "chronicle.envelope_id": envelope.envelope_id,
        "chronicle.trace_id": envelope.trace_id,
        "chronicle.invocation_index": envelope.invocation_index,
    }
    if envelope.metadata.build_id:
        attributes["chronicle.build_id"] = envelope.metadata.build_id
    if envelope.boundary_kind == "llm":
        if envelope.metadata.model_version:
            attributes[S.LLM_MODEL_NAME] = envelope.metadata.model_version
        usage = envelope.action_result.token_usage or {}
        prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
        completion = usage.get("completion_tokens", usage.get("output_tokens"))
        if prompt is not None:
            attributes[S.LLM_TOKEN_COUNT_PROMPT] = int(prompt)
        if completion is not None:
            attributes[S.LLM_TOKEN_COUNT_COMPLETION] = int(completion)
    if envelope.boundary_kind == "tool":
        attributes[S.TOOL_NAME] = envelope.node_id
    return attributes


def instrument_otel(
    tracer: Any | None = None,
    *,
    session: ChronicleSession | None = None,
) -> Callable[[], None]:
    """Emit one OpenTelemetry span per recorded boundary crossing.

    Attaches to ``session`` (default: the active session) via its ``on_record`` hook.
    Spans nest by the run's parent linkage and carry OpenInference attributes. Returns a
    callable that removes the instrumentation.
    """
    trace = _require_trace()
    tracer = tracer or trace.get_tracer("chronicle")
    active = session or get_session()
    spans: dict[str, Any] = {}  # envelope_id -> span, for parent linkage

    def on_record(envelope: Envelope) -> None:
        parent = spans.get(envelope.parent_envelope_id) if envelope.parent_envelope_id else None
        context = trace.set_span_in_context(parent) if parent is not None else None
        span = tracer.start_span(envelope.node_id, context=context)
        for key, value in envelope_span_attributes(envelope).items():
            span.set_attribute(key, value)
        if envelope.action_result.error:
            span.set_status(trace.Status(trace.StatusCode.ERROR, envelope.action_result.error))
        span.end()
        spans[envelope.envelope_id] = span

    active.on_record = on_record

    def uninstrument() -> None:
        if active.on_record is on_record:
            active.on_record = None

    return uninstrument
