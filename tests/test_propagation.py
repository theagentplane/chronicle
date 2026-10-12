"""Propagation: ``traceparent`` extract, inject and the allow-list (design 3.2, 8.2, 8.3)."""

import pytest
from agentplane_primitives.models import TraceContext
from agentplane_primitives.utils import format_traceparent, new_envelope_id, new_trace_id

import chronicle
from chronicle.interfaces.propagation_api import is_allowed_host
from tests.support.in_memory_control_plane import InMemoryControlPlane


def test_extract_reads_a_valid_header_in_any_case() -> None:
    context = TraceContext(trace_id=new_trace_id(), parent_envelope_id=new_envelope_id())
    found = chronicle.extract({"TraceParent": format_traceparent(context)})
    assert found == context


@pytest.mark.parametrize(
    "value",
    ["", "garbage", "00-" + "0" * 32 + "-" + "1" * 16 + "-01", "01-" + "a" * 32 + "-" + "b" * 16],
)
def test_extract_never_raises_on_a_malformed_header(value: str) -> None:
    assert chronicle.extract({"traceparent": value}) is None


def test_span_joins_a_received_trace(control_plane: InMemoryControlPlane) -> None:
    context = TraceContext(trace_id=new_trace_id(), parent_envelope_id=new_envelope_id())
    headers = {"traceparent": format_traceparent(context)}
    with chronicle.span(headers) as session:
        pass
    chronicle.flush()
    assert session.trace_id == context.trace_id
    span = control_plane.spans[(context.trace_id, session.span_id)]
    assert span.parent_envelope_id == context.parent_envelope_id
    assert context.trace_id not in control_plane.traces  # a joining service does not register


def test_a_malformed_header_mints_a_new_trace(control_plane: InMemoryControlPlane) -> None:
    with chronicle.span({"traceparent": "not-a-header"}) as session:
        pass
    chronicle.flush()
    assert session.trace_id in control_plane.traces
    assert control_plane.spans[(session.trace_id, session.span_id)].parent_envelope_id is None


def test_extract_can_be_switched_off(control_plane: InMemoryControlPlane) -> None:
    chronicle.configure(extract=False)
    context = TraceContext(trace_id=new_trace_id(), parent_envelope_id=new_envelope_id())
    with chronicle.span({"traceparent": format_traceparent(context)}) as session:
        pass
    assert session.trace_id != context.trace_id


def test_inject_uses_the_innermost_crossing_as_parent(control_plane: InMemoryControlPlane) -> None:
    @chronicle.boundary("call_peer")
    def call_peer() -> dict[str, str]:
        return chronicle.inject({"accept": "json"})

    with chronicle.record("job") as session:
        headers = call_peer()
    chronicle.flush()
    (envelope,) = control_plane.envelopes_named("call_peer")
    context = chronicle.extract(headers)
    assert context is not None
    assert context.trace_id == session.trace_id
    assert context.parent_envelope_id == envelope.envelope_id
    assert headers["accept"] == "json"


def test_inject_outside_a_crossing_leaves_headers_unchanged(
    control_plane: InMemoryControlPlane,
) -> None:
    with chronicle.record("job"):
        assert chronicle.inject({"a": "b"}) == {"a": "b"}


def test_inject_with_a_url_obeys_the_allow_list(control_plane: InMemoryControlPlane) -> None:
    chronicle.configure(inject_hosts=["agent-b.internal"])

    @chronicle.boundary("call_peer")
    def call_peer(url: str) -> dict[str, str]:
        return chronicle.inject({}, url=url)

    with chronicle.record("job"):
        assert "traceparent" in call_peer("http://agent-b.internal/run")
        assert "traceparent" not in call_peer("https://api.openai.com/v1/chat")


def test_default_is_deny() -> None:
    assert is_allowed_host("http://agent-b.internal/run", ()) is False
    assert is_allowed_host("http://agent-b.internal:9000/run", ("agent-b.internal:9000",)) is True
    assert is_allowed_host("http://AGENT-B.internal/run", ("agent-b.internal",)) is True
