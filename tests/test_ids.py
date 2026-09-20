"""OTel-format ids: trace_id is 16 bytes and envelope_id is 8 bytes, lowercase hex."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

import chronicle
from chronicle import boundary
from chronicle.envelope.schema import ActionResult, ContextMetadata, Envelope, InputState
from chronicle.ids import is_span_id, is_trace_id, new_span_id, new_trace_id


def _env(**overrides) -> Envelope:
    return Envelope(
        node_id="agent",
        metadata=ContextMetadata(model_version="m", build_id="b"),
        input_state=InputState(messages=[]),
        action_result=ActionResult(),
        **overrides,
    )


def test_generated_ids_have_otel_lengths():
    assert len(new_trace_id()) == 32 and is_trace_id(new_trace_id())
    assert len(new_span_id()) == 16 and is_span_id(new_span_id())


@pytest.mark.parametrize(
    "bad",
    ["", "incident-001", "A" * 32, "0" * 32, "a" * 31, "a" * 33, "a" * 16, str(int("1" * 32, 16))],
)
def test_bad_trace_ids_are_rejected(bad):
    assert not is_trace_id(bad)
    with pytest.raises(ValidationError):
        _env(trace_id=bad)


@pytest.mark.parametrize("bad", ["", "env-1", "0" * 16, "a" * 32, "G" * 16])
def test_bad_envelope_ids_are_rejected(bad):
    with pytest.raises(ValidationError):
        _env(envelope_id=bad)
    with pytest.raises(ValidationError):
        _env(parent_envelope_id=bad)


def test_default_envelope_ids_are_valid():
    env = _env()
    assert is_trace_id(env.trace_id) and is_span_id(env.envelope_id)
    assert env.parent_envelope_id is None


def test_otel_named_getters():
    env = _env(dims={"k": "v"})
    assert env.span_id == env.envelope_id
    assert env.parent_span_id is None
    assert env.name == env.node_id == "agent"
    assert env.end_time == env.timestamp
    assert env.start_time == env.timestamp  # no started_at recorded
    assert env.attributes == {"k": "v"}


def test_record_name_is_a_label_not_the_trace_id():
    @boundary("step", kind="tool")
    def step():
        return {"ok": True}

    with chronicle.record("my-incident") as session:
        step()
    assert is_trace_id(session.trace_id)
    (env,) = session.envelopes
    assert env.trace_id == session.trace_id
    assert env.dims["chronicle.trace.name"] == "my-incident"
    assert is_span_id(env.envelope_id)


def test_record_accepts_an_explicit_otel_trace_id_and_rejects_others():
    tid = new_trace_id()
    with chronicle.record(trace_id=tid) as session:
        pass
    assert session.trace_id == tid
    with pytest.raises(ValueError, match="OpenTelemetry trace id"):
        with chronicle.record(trace_id="incident-001"):
            pass


def test_unnamed_trace_has_no_name_dim():
    @boundary("step", kind="tool")
    def step():
        return {"ok": True}

    with chronicle.record() as session:
        step()
    assert "chronicle.trace.name" not in session.envelopes[0].dims
