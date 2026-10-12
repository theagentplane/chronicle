"""Settings that change what is captured: emit_open, capture toggles, extractors, metadata."""

from agentplane_primitives.enums import State
from agentplane_primitives.models import ToolInput, ToolOutput

import chronicle
from tests.support.in_memory_control_plane import InMemoryControlPlane


def test_emit_open_writes_the_input_before_the_call_completes(
    control_plane: InMemoryControlPlane,
) -> None:
    chronicle.configure(emit_open=True)
    seen_while_running: list[State] = []

    @chronicle.boundary("slow")
    def slow(x: int) -> int:
        chronicle.flush()
        (open_record,) = control_plane.envelopes_named("slow")
        seen_while_running.append(open_record.envelope_status.state)
        assert isinstance(open_record.input, ToolInput)
        assert open_record.input.raw == {"x": 3}
        assert open_record.output is None
        return x + 1

    with chronicle.record("job"):
        assert slow(3) == 4
    chronicle.flush()

    assert seen_while_running == [State.OPEN]
    (final,) = control_plane.envelopes_named("slow")  # one record, updated at close
    assert final.envelope_status.state is State.CLOSED
    assert isinstance(final.output, ToolOutput)
    assert final.output.raw == 4


def test_by_default_only_the_close_write_is_sent(control_plane: InMemoryControlPlane) -> None:
    @chronicle.boundary("quick")
    def quick() -> int:
        chronicle.flush()
        assert control_plane.envelopes_named("quick") == []
        return 1

    with chronicle.record("job"):
        quick()


def test_capture_toggles_drop_payloads_but_keep_the_record(
    control_plane: InMemoryControlPlane,
) -> None:
    chronicle.configure(capture_input=False, capture_output=False)

    @chronicle.boundary("private")
    def private(secret: str) -> str:
        return f"echo {secret}"

    with chronicle.record("job"):
        assert private("hunter2") == "echo hunter2"
    chronicle.flush()

    (envelope,) = control_plane.envelopes_named("private")
    assert isinstance(envelope.input, ToolInput)
    assert isinstance(envelope.output, ToolOutput)
    assert envelope.input.raw == {}
    assert envelope.output.raw is None


def test_extractors_shape_the_record_not_the_return_value(
    control_plane: InMemoryControlPlane,
) -> None:
    @chronicle.boundary(
        "shaped",
        extract_input=lambda *args, **kwargs: {"only": "this"},
        extract_result=lambda result: {"summary": result["value"]},
        extract_metadata=lambda result: {"retrieval.source": "cache", "Bad Key!": 1},
    )
    def shaped(a: int) -> dict[str, int]:
        return {"value": a * 2, "noise": 1}

    with chronicle.record("job"):
        assert shaped(4) == {"value": 8, "noise": 1}  # the caller still gets the real result
    chronicle.flush()

    (envelope,) = control_plane.envelopes_named("shaped")
    assert isinstance(envelope.input, ToolInput)
    assert isinstance(envelope.output, ToolOutput)
    assert envelope.input.raw == {"only": "this"}
    assert envelope.output.raw == {"summary": 8}
    assert envelope.metadata["retrieval.source"] == "cache"
    assert "Bad Key!" not in envelope.metadata  # invalid metadata keys are dropped, not fatal


def test_a_recording_failure_never_breaks_the_call(control_plane: InMemoryControlPlane) -> None:
    @chronicle.boundary("odd", extract_input=lambda *a, **k: 1 / 0)  # type: ignore[arg-type,return-value]
    def odd() -> str:
        return "still works"

    with chronicle.record("job"):
        assert odd() == "still works"


def test_ambient_span_records_calls_made_outside_any_span(
    control_plane: InMemoryControlPlane,
) -> None:
    @chronicle.boundary("script.step")
    def step() -> int:
        return 5

    assert step() == 5
    chronicle.shutdown()
    (envelope,) = control_plane.envelopes_named("script.step")
    (span,) = control_plane.spans.values()
    assert envelope.span_id == span.span_id
    assert span.state is State.CLOSED
