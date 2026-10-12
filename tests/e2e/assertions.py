"""Assertions shared by the topology tests: what every multi-agent trace must satisfy."""

import time

from agentplane_primitives.enums import Kind, State, Status
from agentplane_primitives.models import Envelope, LlmOutput, Span, ToolInput, ToolOutput

import chronicle
from tests.e2e.system import System
from tests.support.fake_llm_server import FakeLlmServer


def settle(system: System, timeout: float = 10.0) -> None:
    """Wait until every opened span is closed and delivered to the fake control plane.

    A span closes after its response has been sent, so the caller can see the answer a moment
    before the control plane sees the close write.
    """
    deadline = time.monotonic() + timeout
    while True:
        chronicle.flush()
        spans = list(system.plane.spans.values())
        if spans and all(s.state is State.CLOSED for s in spans):
            return
        if time.monotonic() > deadline:
            return
        time.sleep(0.02)


def trace_ids(system: System) -> set[str]:
    settle(system)
    return {span.trace_id for span in system.plane.spans.values()}


def span_of(system: System, service: str) -> Span:
    (trace_id,) = trace_ids(system)
    return system.plane.span_for(trace_id, service)


def envelopes(system: System, service: str) -> list[Envelope]:
    return system.plane.envelopes_of(span_of(system, service))


def outbound_call(system: System, caller: str, path_suffix: str) -> Envelope:
    """The caller's outbound HTTP tool envelope whose name ends with ``path_suffix``."""
    matches = [
        e
        for e in envelopes(system, caller)
        if e.kind is Kind.TOOL and e.name.startswith("http ") and e.name.endswith(path_suffix)
    ]
    assert len(matches) == 1, [e.name for e in envelopes(system, caller)]
    return matches[0]


def assert_linked(system: System, caller: str, callee: str, path_suffix: str = "/run") -> None:
    """The callee's span is parented on the caller's outbound-call envelope."""
    outbound = outbound_call(system, caller, path_suffix)
    assert span_of(system, callee).parent_envelope_id == outbound.envelope_id


def assert_well_formed_trace(system: System, services: list[str]) -> None:
    """One trace, one span per service, closed and successful, only llm and tool envelopes."""
    settle(system)
    assert len(trace_ids(system)) == 1
    (trace_id,) = trace_ids(system)
    assert trace_id in system.plane.traces
    spans = [s for s in system.plane.spans.values() if s.trace_id == trace_id]
    assert sorted(s.service for s in spans) == sorted(services)
    for span in spans:
        assert span.state is State.CLOSED
        assert span.status is Status.SUCCESS
    assert system.plane.rejected == []  # every payload validated against the primitives models
    for envelope in system.plane.envelopes.values():
        assert envelope.kind in (Kind.LLM, Kind.TOOL)
        assert envelope.envelope_status.state is State.CLOSED


def assert_cost_fields(envelope: Envelope, provider: str) -> None:
    """The fixed homes for pricing consumers are filled the same way for every framework."""
    assert envelope.kind is Kind.LLM
    output = envelope.output
    assert isinstance(output, LlmOutput)
    assert output.provider == provider
    assert output.model
    assert output.model_source is not None
    assert output.usage is not None
    assert output.usage.input + output.usage.output > 0
    assert output.raw is not None  # raw input and output are stored
    assert envelope.input.raw


def llm_envelopes(system: System, service: str) -> list[Envelope]:
    return [e for e in envelopes(system, service) if e.kind is Kind.LLM]


def tool_envelopes(system: System, service: str) -> list[Envelope]:
    return [e for e in envelopes(system, service) if e.kind is Kind.TOOL]


def assert_no_traceparent_sent_to_provider(*providers: FakeLlmServer) -> None:
    """The header goes to peers, never to the LLM provider host (allow-list default deny)."""
    for provider in providers:
        assert provider.requests, "the provider was never called"
        for request in provider.requests:
            assert "traceparent" not in request.headers


def tool_raw_input(envelope: Envelope) -> dict[str, object]:
    assert isinstance(envelope.input, ToolInput)
    return dict(envelope.input.raw)


def tool_raw_output(envelope: Envelope) -> object:
    assert isinstance(envelope.output, ToolOutput)
    return envelope.output.raw
