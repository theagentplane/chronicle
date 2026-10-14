"""Record: one request produces a trace, a span and envelopes, and never alters the call."""

import asyncio

import pytest
from agentplane_primitives.enums import Kind, State, Status
from agentplane_primitives.models import ToolInput, ToolOutput

import chronicle
from tests.support.in_memory_control_plane import InMemoryControlPlane


def test_tool_call_is_recorded_with_arguments_by_name(control_plane: InMemoryControlPlane) -> None:
    @chronicle.boundary("add")
    def add(a: int, b: int = 2) -> int:
        return a + b

    with chronicle.record("demo") as session:
        assert add(1, b=5) == 6

    (envelope,) = control_plane.envelopes_named("add")
    assert envelope.kind is Kind.TOOL
    assert envelope.span_id == session.span_id
    assert envelope.envelope_status.state is State.CLOSED
    assert envelope.envelope_status.status is Status.SUCCESS
    assert isinstance(envelope.input, ToolInput)
    assert envelope.input.raw == {"a": 1, "b": 5}
    assert isinstance(envelope.output, ToolOutput)
    assert envelope.output.raw == 6
    assert envelope.metadata["chronicle.invocation_index"] == 1


def test_trace_and_span_are_written(control_plane: InMemoryControlPlane) -> None:
    @chronicle.boundary("noop")
    def noop() -> None:
        return None

    with chronicle.record("job", labels={"session_id": "s1"}) as session:
        noop()

    trace = control_plane.traces[session.trace_id]
    assert trace.name == "job"
    assert trace.metadata == {"session_id": "s1"}
    span = control_plane.spans[(session.trace_id, session.span_id)]
    assert span.state is State.CLOSED
    assert span.status is Status.SUCCESS
    assert span.parent_envelope_id is None
    # the open span reaches the control plane before its envelopes
    order = control_plane.order
    assert order.index(f"span:open:{session.span_id}") < order.index("envelope:noop")


def test_failure_is_recorded_and_reraised(control_plane: InMemoryControlPlane) -> None:
    @chronicle.boundary("boom")
    def boom() -> None:
        raise KeyError("missing")

    with pytest.raises(KeyError), chronicle.record("job"):
        boom()

    (envelope,) = control_plane.envelopes_named("boom")
    assert envelope.envelope_status.status is Status.FAILURE
    assert isinstance(envelope.output, ToolOutput)
    assert envelope.output.error is not None
    assert envelope.output.error.type == "KeyError"
    (span,) = control_plane.spans.values()
    assert span.status is Status.FAILURE


def test_handled_failure_does_not_fail_the_span(control_plane: InMemoryControlPlane) -> None:
    @chronicle.boundary("flaky")
    def flaky() -> None:
        raise RuntimeError("once")

    with chronicle.record("job"), pytest.raises(RuntimeError):
        flaky()

    (span,) = control_plane.spans.values()
    assert span.status is Status.SUCCESS


def test_nested_boundaries_parent_correctly(control_plane: InMemoryControlPlane) -> None:
    @chronicle.boundary("inner")
    def inner() -> int:
        return 1

    @chronicle.boundary("outer")
    def outer() -> int:
        return inner() + inner()

    with chronicle.record("job"):
        outer()

    (outer_env,) = control_plane.envelopes_named("outer")
    inner_envs = control_plane.envelopes_named("inner")
    assert outer_env.parent_envelope_id is None
    assert [e.parent_envelope_id for e in inner_envs] == [outer_env.envelope_id] * 2
    assert [e.metadata["chronicle.invocation_index"] for e in inner_envs] == [1, 2]


def test_async_boundary(control_plane: InMemoryControlPlane) -> None:
    @chronicle.boundary("fetch")
    async def fetch(x: int) -> int:
        return x * 2

    async def main() -> int:
        async with chronicle.aspan():
            return await fetch(4)

    assert asyncio.run(main()) == 8
    (envelope,) = control_plane.envelopes_named("fetch")
    assert isinstance(envelope.output, ToolOutput)
    assert envelope.output.raw == 8


def test_unknown_kind_fails_at_declaration() -> None:
    with pytest.raises(ValueError, match="retired"):

        @chronicle.boundary("x", kind="router")
        def x() -> None:
            return None


def test_retry_is_declared_with_attempt(control_plane: InMemoryControlPlane) -> None:
    @chronicle.boundary("call")
    def call() -> int:
        return 1

    with chronicle.record("job"):
        call()
        chronicle.flush()
        (first,) = control_plane.envelopes_named("call")
        with chronicle.attempt(2, of=first.envelope_id):
            call()

    first, second = control_plane.envelopes_named("call")
    assert first.attempt == 1
    assert second.attempt == 2
    assert [(link.type.value, link.envelope_id) for link in second.links] == [
        ("retry_of", first.envelope_id)
    ]
