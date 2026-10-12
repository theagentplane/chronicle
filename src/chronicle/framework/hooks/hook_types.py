"""Hook types: the ``Hook`` base class, ``CallInfo`` and ``AbortCall`` (design section 4.4).

There is one kind of hook, a callback with four events: ``enter`` (before the call; may patch
keyword arguments or abort), ``leave`` (after, always, if ``enter`` succeeded), ``crossing`` (the
call returned and was captured) and ``record`` (the envelope was written). A governor stops a call
on purpose by raising ``AbortCall``, which always propagates whatever the failure flag says.

**Security surface (future scope).** Hooks currently see the arguments before redaction and the
live result object, and can change arguments. What hooks may see and do needs its own review.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from agentplane_primitives.enums import Kind
from agentplane_primitives.models import Envelope
from pydantic import JsonValue


class AbortCall(Exception):
    """Raised by a hook to stop a call on purpose.

    It is recorded as a failure with ``output.error.type = "AbortCall"`` and always propagates to
    the caller, whatever ``hooks.fail_call_on_error`` says.
    """


@dataclass(frozen=True)
class CallInfo:
    """What a hook is told about one crossing.

    ``arguments`` is the JSON form of the bound arguments by name, before redaction.
    """

    name: str
    kind: Kind
    arguments: dict[str, JsonValue]
    invocation_index: int
    attempt: int
    trace_id: str
    span_id: str
    envelope_id: str


class Hook:
    """Base class for hooks. Override only the events you need; every method is a no-op."""

    def enter(self, call: CallInfo) -> Mapping[str, Any] | None:
        """Before the call. Return keyword arguments to merge into the call, or ``None``."""
        return None

    def leave(self, call: CallInfo) -> None:
        """After the call, always, if ``enter`` succeeded."""

    def crossing(self, call: CallInfo, result: Any) -> None:
        """The call returned and was captured. ``result`` is the live return value."""

    def record(self, envelope: Envelope) -> None:
        """The envelope was written (RECORD sessions only)."""


class FunctionHook(Hook):
    """A hook built from plain callables, for when a subclass is more than you need."""

    def __init__(
        self,
        *,
        enter: Callable[[CallInfo], Mapping[str, Any] | None] | None = None,
        leave: Callable[[CallInfo], None] | None = None,
        crossing: Callable[[CallInfo, Any], None] | None = None,
        record: Callable[[Envelope], None] | None = None,
    ) -> None:
        self._enter = enter
        self._leave = leave
        self._crossing = crossing
        self._record = record

    def enter(self, call: CallInfo) -> Mapping[str, Any] | None:
        return self._enter(call) if self._enter is not None else None

    def leave(self, call: CallInfo) -> None:
        if self._leave is not None:
            self._leave(call)

    def crossing(self, call: CallInfo, result: Any) -> None:
        if self._crossing is not None:
            self._crossing(call, result)

    def record(self, envelope: Envelope) -> None:
        if self._record is not None:
            self._record(envelope)
