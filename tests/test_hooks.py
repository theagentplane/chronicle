"""Hooks: one kind, four events, ordered, with AbortCall always propagating (design 4.4)."""

from typing import Any

import pytest
from agentplane_primitives.enums import Status
from agentplane_primitives.models import Envelope, ToolOutput

import chronicle
from chronicle import AbortCall, CallInfo, FunctionHook, Hook
from chronicle.framework.hooks.hook_registry import default_hooks
from tests.support.in_memory_control_plane import InMemoryControlPlane


@chronicle.boundary("greet")
def greet(name: str, punctuation: str = "!") -> str:
    return f"hello {name}{punctuation}"


class Recorder(Hook):
    def __init__(self, log: list[str], label: str = "") -> None:
        self.log = log
        self.label = label

    def enter(self, call: CallInfo) -> None:
        self.log.append(f"{self.label}enter:{call.name}")

    def crossing(self, call: CallInfo, result: Any) -> None:
        self.log.append(f"{self.label}crossing:{result}")

    def record(self, envelope: Envelope) -> None:
        self.log.append(f"{self.label}record:{envelope.name}")

    def leave(self, call: CallInfo) -> None:
        self.log.append(f"{self.label}leave")


def test_events_run_in_order_around_the_call(control_plane: InMemoryControlPlane) -> None:
    log: list[str] = []
    default_hooks.register(Recorder(log))
    with chronicle.record("job"):
        assert greet("ada") == "hello ada!"
    assert log == ["enter:greet", "crossing:hello ada!", "record:greet", "leave"]


def test_hooks_run_in_registration_order(control_plane: InMemoryControlPlane) -> None:
    log: list[str] = []
    default_hooks.register(Recorder(log, "a:"))
    default_hooks.register(Recorder(log, "b:"))
    with chronicle.record("job"):
        greet("ada")
    assert log[:2] == ["a:enter:greet", "b:enter:greet"]


def test_enter_patches_are_merged_and_the_later_wins(control_plane: InMemoryControlPlane) -> None:
    default_hooks.register(FunctionHook(enter=lambda call: {"punctuation": "?"}))
    default_hooks.register(FunctionHook(enter=lambda call: {"punctuation": "."}))
    with chronicle.record("job"):
        assert greet("ada") == "hello ada."


def test_a_failing_hook_is_logged_and_the_call_continues(
    control_plane: InMemoryControlPlane,
) -> None:
    def explode(call: CallInfo) -> None:
        raise RuntimeError("hook bug")

    default_hooks.register(FunctionHook(enter=explode))
    with chronicle.record("job"):
        assert greet("ada") == "hello ada!"


def test_fail_call_on_error_makes_a_hook_failure_fail_the_call(
    control_plane: InMemoryControlPlane,
) -> None:
    chronicle.configure(hooks_fail_call_on_error=True)

    def explode(call: CallInfo) -> None:
        raise RuntimeError("hook bug")

    default_hooks.register(FunctionHook(enter=explode))
    with pytest.raises(RuntimeError, match="hook bug"), chronicle.record("job"):
        greet("ada")


@pytest.mark.parametrize("fail_flag", [False, True])
def test_abort_call_always_propagates_and_is_recorded(
    control_plane: InMemoryControlPlane, fail_flag: bool
) -> None:
    chronicle.configure(hooks_fail_call_on_error=fail_flag)
    ran: list[str] = []

    @chronicle.boundary("guarded")
    def guarded() -> None:
        ran.append("ran")

    def halt(call: CallInfo) -> None:
        raise AbortCall("budget exhausted")

    default_hooks.register(FunctionHook(enter=halt))
    with pytest.raises(AbortCall), chronicle.record("job"):
        guarded()

    assert ran == []  # the call never ran
    chronicle.flush()
    (envelope,) = control_plane.envelopes_named("guarded")
    assert envelope.envelope_status.status is Status.FAILURE
    assert isinstance(envelope.output, ToolOutput)
    assert envelope.output.error is not None
    assert envelope.output.error.type == "AbortCall"


def test_leave_runs_when_the_call_raises(control_plane: InMemoryControlPlane) -> None:
    log: list[str] = []
    default_hooks.register(Recorder(log))

    @chronicle.boundary("bad")
    def bad() -> None:
        raise ValueError("no")

    with pytest.raises(ValueError, match="no"), chronicle.record("job"):
        bad()
    assert log == ["enter:bad", "record:bad", "leave"]


def test_hooks_still_run_when_recording_is_disabled(control_plane: InMemoryControlPlane) -> None:
    """Decision for issue #60: ``enabled = false`` stops recording, not governance."""
    chronicle.configure(enabled=False)
    log: list[str] = []
    default_hooks.register(Recorder(log))
    assert greet("ada") == "hello ada!"
    assert log == ["enter:greet", "crossing:hello ada!", "leave"]
    chronicle.flush()
    assert control_plane.all_envelopes() == []
    assert control_plane.traces == {}
