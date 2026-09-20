"""First-class OpenTelemetry export: one span per boundary crossing, carrying
OpenInference attributes and nested by the run's call graph. Uses an in-memory exporter.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

pytest.importorskip("opentelemetry")
pytest.importorskip("openinference.semconv")

from openinference.semconv.trace import OpenInferenceSpanKindValues as Kind
from openinference.semconv.trace import SpanAttributes as S
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

import chronicle
from chronicle import boundary


def _tracer_and_exporter():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("test"), exporter


def _run_agent():
    @boundary("agent", kind="llm")
    def agent(state):
        return {**state, "completion": "plan", "tool_calls": [], "finish_reason": "tool_calls"}

    @boundary("refund", kind="tool")
    def refund(order_id, amount_cents):
        return {"status": "blocked", "blocked": True, "amount_cents": amount_cents}

    @boundary("agent", kind="llm")
    def finalize(state, tool_result):
        return {**state, "completion": "done", "blocked": tool_result["blocked"]}

    state = agent({"messages": []})
    tool_result = refund("o1", 999)
    return finalize(state, tool_result)


def _run_nested_agent():
    """True call-stack nesting: tool runs inside the outer agent boundary."""

    @boundary("refund", kind="tool")
    def refund(order_id, amount_cents):
        return {"status": "blocked", "blocked": True, "amount_cents": amount_cents}

    @boundary("agent", kind="llm")
    def agent(state):
        tool_result = refund("o1", 999)
        return {**state, "completion": "done", "blocked": tool_result["blocked"]}

    return agent({"messages": []})


def test_one_span_per_crossing_with_openinference_attrs():
    tracer, exporter = _tracer_and_exporter()
    with chronicle.record("t-otel") as session:
        chronicle.instrument_otel(tracer=tracer)
        _run_agent()

    spans = exporter.get_finished_spans()
    assert [s.name for s in spans] == ["agent", "refund", "agent"]
    kinds = [s.attributes[S.OPENINFERENCE_SPAN_KIND] for s in spans]
    assert kinds == [Kind.LLM.value, Kind.TOOL.value, Kind.LLM.value]
    for span in spans:
        assert S.INPUT_VALUE in span.attributes
        assert S.OUTPUT_VALUE in span.attributes
        assert span.attributes["chronicle.trace.name"] == "t-otel"
    assert spans[1].attributes[S.TOOL_NAME] == "refund"


def test_spans_nest_by_parent_linkage():
    tracer, exporter = _tracer_and_exporter()
    with chronicle.record("t-nest"):
        chronicle.instrument_otel(tracer=tracer)
        _run_nested_agent()

    finished = exporter.get_finished_spans()
    # Child (refund) finishes before parent (agent) — export order is end order.
    by_name = {s.name: s for s in finished}
    assert by_name["agent"].parent is None
    assert by_name["refund"].parent is not None
    assert by_name["refund"].parent.span_id == by_name["agent"].context.span_id


def test_sequential_top_level_spans_are_siblings():
    tracer, exporter = _tracer_and_exporter()
    with chronicle.record("t-sib"):
        chronicle.instrument_otel(tracer=tracer)
        _run_agent()

    spans = exporter.get_finished_spans()
    assert all(s.parent is None for s in spans)


def test_error_boundary_sets_error_status():
    tracer, exporter = _tracer_and_exporter()

    @boundary("boom", kind="tool")
    def boom():
        raise ValueError("nope")

    with chronicle.record("t-err"):
        chronicle.instrument_otel(tracer=tracer)
        with pytest.raises(ValueError):
            boom()

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].status.status_code == StatusCode.ERROR


def test_uninstrument_stops_spans():
    tracer, exporter = _tracer_and_exporter()
    with chronicle.record("t-un") as session:
        stop = chronicle.instrument_otel(tracer=tracer, session=session)
        _run_agent()
        stop()
        _run_agent()
    assert len(exporter.get_finished_spans()) == 3  # only the first run emitted spans


def test_attribute_mapping_includes_model_and_tokens():
    from chronicle.envelope.schema import Output, Metadata, Envelope, Input

    env = Envelope(
        name="llm",
        kind="llm",
        metadata=Metadata(model="gpt-4o"),
        input=Input(messages=[{"role": "user", "content": "hi"}]),
        output=Output(
            completion="hey", token_usage={"prompt_tokens": 3, "completion_tokens": 2}
        ),
    )
    attrs = chronicle.envelope_span_attributes(env)
    assert attrs[S.OPENINFERENCE_SPAN_KIND] == Kind.LLM.value
    assert attrs[S.LLM_MODEL_NAME] == "gpt-4o"
    assert attrs[S.LLM_TOKEN_COUNT_PROMPT] == 3
    assert attrs[S.LLM_TOKEN_COUNT_COMPLETION] == 2


def test_import_chronicle_does_not_import_opentelemetry():
    code = "import chronicle, sys; assert 'chronicle.otel' not in sys.modules; print('ok')"
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ok"


def test_exported_spans_carry_the_envelope_ids():
    """Envelope ids are already OTel-format, so the span reuses them unchanged."""
    tracer, exporter = _tracer_and_exporter()
    with chronicle.record("t-ids") as session:
        chronicle.instrument_otel(tracer=tracer)
        _run_nested_agent()

    by_name = {s.name: s for s in exporter.get_finished_spans()}
    envelopes = {e.name: e for e in session.envelopes}
    for name, span in by_name.items():
        env = envelopes[name]
        assert format(span.context.trace_id, "032x") == env.trace_id == session.trace_id
        assert format(span.context.span_id, "016x") == env.span_id == env.envelope_id
    child = envelopes["refund"]
    assert format(by_name["refund"].parent.span_id, "016x") == child.parent_span_id


def test_exported_span_times_match_the_envelope():
    tracer, exporter = _tracer_and_exporter()
    with chronicle.record("t-time") as session:
        chronicle.instrument_otel(tracer=tracer)
        _run_agent()

    for span, env in zip(exporter.get_finished_spans(), session.envelopes):
        assert span.end_time == int(env.end_time.timestamp() * 1_000_000_000)
        assert span.start_time == int(env.start_time.timestamp() * 1_000_000_000)
        assert span.start_time <= span.end_time
