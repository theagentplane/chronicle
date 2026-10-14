"""Delivery: non-blocking enqueue, ordered batches, flush, overflow, fail-open and strict."""

import threading
import time
from collections.abc import Sequence

import pytest
from agentplane_primitives.models import Envelope, Span, Trace

import chronicle
from chronicle.config import OverflowPolicy
from chronicle.repositories import (
    ControlPlaneError,
    DeliveryError,
    DeliveryPolicy,
    QueuedEnvelopeSink,
    RegistrationError,
)
from tests.support.in_memory_control_plane import InMemoryControlPlane


def _span_and_envelope() -> tuple[Span, Envelope]:
    plane = InMemoryControlPlane()
    chronicle.configure(client=plane, batch_size=1, flush_interval=0.01)

    @chronicle.boundary("t")
    def t() -> int:
        return 1

    with chronicle.record("x"):
        t()
    chronicle.flush()
    span = next(iter(plane.spans.values()))
    envelope = next(iter(plane.envelopes.values()))
    chronicle.reset()
    return span, envelope


class SlowPlane(InMemoryControlPlane):
    def __init__(self) -> None:
        super().__init__()
        self.gate = threading.Event()
        self.batches: list[int] = []

    def append_envelopes(self, envelopes: Sequence[Envelope]) -> None:
        self.gate.wait(timeout=5)
        self.batches.append(len(envelopes))
        super().append_envelopes(envelopes)


def test_envelopes_are_batched_and_order_is_kept() -> None:
    span, envelope = _span_and_envelope()
    plane = InMemoryControlPlane()
    sink = QueuedEnvelopeSink(plane, DeliveryPolicy(batch_size=3, flush_interval=5))
    sink.write_span(span)
    for i in range(7):
        sink.write_envelope(envelope.model_copy(update={"name": f"e{i}"}))
    sink.flush()
    assert plane.order[0].startswith("span:")
    assert plane.order[1:] == [f"envelope:e{i}" for i in range(7)]
    sink.close()


def test_write_does_not_block_on_the_network() -> None:
    _, envelope = _span_and_envelope()
    plane = SlowPlane()
    sink = QueuedEnvelopeSink(plane, DeliveryPolicy(batch_size=1))
    started = time.monotonic()
    sink.write_envelope(envelope)
    assert time.monotonic() - started < 0.5  # enqueue returns while delivery is stuck
    plane.gate.set()
    sink.flush()
    assert plane.batches == [1]
    sink.close()


def test_overflow_drop_counts_dropped_records() -> None:
    _, envelope = _span_and_envelope()
    plane = SlowPlane()
    sink = QueuedEnvelopeSink(
        plane, DeliveryPolicy(batch_size=1, max_queue=2, on_overflow=OverflowPolicy.DROP)
    )
    for _ in range(10):
        sink.write_envelope(envelope)
    assert sink.dropped >= 1
    plane.gate.set()
    sink.close()


def test_fail_open_swallows_delivery_errors() -> None:
    span, envelope = _span_and_envelope()
    plane = InMemoryControlPlane()
    plane.fail_with = ControlPlaneError("down")
    sink = QueuedEnvelopeSink(plane, DeliveryPolicy(batch_size=1, fail_open=True))
    sink.write_span(span)
    sink.write_envelope(envelope)
    sink.flush()  # does not raise
    sink.close()


def test_strict_raises_at_flush() -> None:
    _, envelope = _span_and_envelope()
    plane = InMemoryControlPlane()
    plane.fail_with = ControlPlaneError("down")
    sink = QueuedEnvelopeSink(plane, DeliveryPolicy(batch_size=1, fail_open=False))
    sink.write_envelope(envelope)
    with pytest.raises(DeliveryError):
        sink.flush()
    sink.close()


def test_span_end_flushes_the_queue(control_plane: InMemoryControlPlane) -> None:
    chronicle.configure(batch_size=100, flush_interval=60)

    @chronicle.boundary("t")
    def t() -> int:
        return 1

    with chronicle.record("x") as session:
        t()
    # no explicit flush: leaving the span flushed everything, even with a huge batch size
    assert control_plane.envelopes_named("t")
    assert control_plane.spans[(session.trace_id, session.span_id)].state.value == "closed"


def test_control_plane_down_fail_open_agent_still_works(
    control_plane: InMemoryControlPlane,
) -> None:
    control_plane.fail_with = ControlPlaneError("down")

    @chronicle.boundary("t")
    def t() -> int:
        return 41 + 1

    with chronicle.record("x"):
        assert t() == 42


def test_strict_trace_registration_fails_the_request(control_plane: InMemoryControlPlane) -> None:
    chronicle.configure(registration_fail_open=False)
    control_plane.fail_with = ControlPlaneError("down")
    with pytest.raises(RegistrationError), chronicle.record("x"):
        pass


def test_strict_delivery_fails_the_request_at_span_end(
    control_plane: InMemoryControlPlane,
) -> None:
    chronicle.configure(fail_open=False, registration_fail_open=True)

    @chronicle.boundary("t")
    def t() -> int:
        control_plane.fail_with = ControlPlaneError("down")
        return 1

    with pytest.raises(DeliveryError), chronicle.record("x"):
        t()


def test_lazy_registration_does_not_call_the_control_plane(
    control_plane: InMemoryControlPlane,
) -> None:
    chronicle.configure(trace_registration="lazy")
    with chronicle.record("x"):
        pass
    assert control_plane.traces == {}
    assert len(control_plane.spans) == 1


def test_trace_has_no_state_of_its_own_beyond_open() -> None:
    trace = Trace(trace_id="a" * 32, state="open")  # type: ignore[arg-type]
    assert trace.state.value == "open"
