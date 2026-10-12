"""Redaction: applied to the JSON form before anything is sent (design section 4.5)."""

import contextlib

from agentplane_primitives.models import ToolInput, ToolOutput
from pydantic import JsonValue

import chronicle
from chronicle.framework.redaction import REDACTED, default_redactors, redact_json
from tests.support.in_memory_control_plane import InMemoryControlPlane

SECRET = "sk-" + "a1b2c3d4e5f6g7h8i9j0"


def test_redact_json_scrubs_values_not_keys() -> None:
    value: JsonValue = {
        "sk-keyname-should-stay-12345": [SECRET, {"nested": f"use {SECRET} now"}],
        "n": 3,
    }
    redacted = redact_json(value, default_redactors())
    assert redacted == {
        "sk-keyname-should-stay-12345": [REDACTED, {"nested": f"use {REDACTED} now"}],
        "n": 3,
    }


def test_redaction_is_off_by_default(control_plane: InMemoryControlPlane) -> None:
    @chronicle.boundary("echo")
    def echo(text: str) -> str:
        return text

    with chronicle.record("job"):
        echo(SECRET)
    chronicle.flush()
    (envelope,) = control_plane.envelopes_named("echo")
    assert isinstance(envelope.input, ToolInput)
    assert envelope.input.raw == {"text": SECRET}


def test_default_redactors_mask_input_output_and_error(
    control_plane: InMemoryControlPlane,
) -> None:
    chronicle.configure(default_redactors=True)

    @chronicle.boundary("echo")
    def echo(text: str) -> str:
        return f"got {text}"

    @chronicle.boundary("leak")
    def leak(text: str) -> None:
        raise RuntimeError(f"bad key {text}")

    with chronicle.record("job"):
        assert echo(SECRET) == f"got {SECRET}"  # the caller still gets the real value
        with contextlib.suppress(RuntimeError):
            leak(SECRET)
    chronicle.flush()

    (ok,) = control_plane.envelopes_named("echo")
    assert isinstance(ok.input, ToolInput)
    assert isinstance(ok.output, ToolOutput)
    assert ok.input.raw == {"text": REDACTED}
    assert ok.output.raw == f"got {REDACTED}"
    (failed,) = control_plane.envelopes_named("leak")
    assert isinstance(failed.output, ToolOutput)
    assert failed.output.error is not None
    assert SECRET not in failed.output.error.message
    assert SECRET not in "".join(e.model_dump_json() for e in control_plane.all_envelopes())


def test_custom_redactors_run_after_the_defaults(control_plane: InMemoryControlPlane) -> None:
    chronicle.configure(redactors=[lambda s: s.replace("alice", "<user>")])

    @chronicle.boundary("echo")
    def echo(text: str) -> str:
        return text

    with chronicle.record("job"):
        echo("hi alice")
    chronicle.flush()
    (envelope,) = control_plane.envelopes_named("echo")
    assert isinstance(envelope.output, ToolOutput)
    assert envelope.output.raw == "hi <user>"


def test_long_strings_are_truncated(control_plane: InMemoryControlPlane) -> None:
    chronicle.configure(max_payload_bytes=10)

    @chronicle.boundary("echo")
    def echo(text: str) -> str:
        return text

    with chronicle.record("job"):
        echo("x" * 100)
    chronicle.flush()
    (envelope,) = control_plane.envelopes_named("echo")
    assert isinstance(envelope.input, ToolInput)
    assert str(envelope.input.raw["text"]).startswith("x" * 10)
    assert len(str(envelope.input.raw["text"])) < 100
    assert envelope.metadata["chronicle.truncated"] is True
