"""``ReplayState``: the cursor, recording and captures of one replay (design 7.2, 7.3, 7.5).

Implements ``ReplayControl`` for the interceptor. Everything here is in memory and none of it is a
persisted entity (design section 2.7).

- **STUB**: take the next recorded envelope for that boundary name (the cursor) and hand back its
  ``output.raw``. No hooks fire.
- **RUN**: execute the real function. Nothing is written; input and result are kept in memory
  (``captured_input`` and ``captured_result``). The cursor advances even if the call raises.
"""

import threading
from dataclasses import dataclass
from typing import Any

from agentplane_primitives.enums import Status
from agentplane_primitives.models import Envelope
from pydantic import JsonValue

from chronicle.capabilities.replay.recording_index_utils import build_index
from chronicle.capabilities.replay.replay_plan_types import ReplayPlan
from chronicle.framework.boundary_enums import BoundaryMode
from chronicle.framework.errors import ReplayMismatchError


@dataclass(frozen=True)
class CallRecord:
    """One crossing seen during replay."""

    name: str
    invocation_index: int
    mode: BoundaryMode


class ReplayState:
    """Serves one span's recording to the interceptor."""

    def __init__(self, envelopes: list[Envelope], plan: ReplayPlan | None = None) -> None:
        self.envelopes = list(envelopes)
        self.plan = plan or ReplayPlan()
        self._index = build_index(self.envelopes)
        self._cursor: dict[str, int] = {}
        self._inputs: dict[tuple[str, int], dict[str, JsonValue]] = {}
        self._results: dict[tuple[str, int], Any] = {}
        self._log: list[CallRecord] = []
        self._lock = threading.Lock()

    # ---- ReplayControl -------------------------------------------------------------------

    def next_invocation(self, name: str) -> int:
        with self._lock:
            count = self._cursor.get(name, 0) + 1
            self._cursor[name] = count
            return count

    def mode_for(self, name: str, invocation_index: int) -> BoundaryMode:
        mode = self.plan.mode_for(name, invocation_index)
        with self._lock:
            self._log.append(CallRecord(name, invocation_index, mode))
        return mode

    def take(self, name: str, invocation_index: int) -> Envelope:
        recorded = self._index.get(name, [])
        if invocation_index > len(recorded):
            raise ReplayMismatchError(
                f"boundary {name!r} was called {invocation_index} time(s) in replay but only "
                f"{len(recorded)} call(s) were recorded (matching is by name plus call count)"
            )
        return recorded[invocation_index - 1]

    def capture(
        self, name: str, invocation_index: int, arguments: dict[str, JsonValue], result: Any
    ) -> None:
        with self._lock:
            self._inputs[(name, invocation_index)] = arguments
            self._results[(name, invocation_index)] = result

    # ---- what tests assert on --------------------------------------------------------------

    def captured_input(self, name: str, invocation_index: int) -> dict[str, JsonValue] | None:
        """The arguments of the ``invocation_index``-th RUN call of ``name``, if it ran."""
        return self._inputs.get((name, invocation_index))

    def captured_result(self, name: str, invocation_index: int) -> Any:
        """The return value of the ``invocation_index``-th RUN call of ``name``, if it ran."""
        return self._results.get((name, invocation_index))

    def call_log(self) -> list[CallRecord]:
        """Every crossing seen, in order, with the mode it ran in."""
        return list(self._log)

    def invocation_count(self, name: str) -> int:
        """How many times ``name`` was called in this replay."""
        return self._cursor.get(name, 0)

    def recorded_failures(self) -> list[Envelope]:
        """The recorded envelopes that failed (useful to pick what to replay)."""
        return [e for e in self.envelopes if e.envelope_status.status is Status.FAILURE]
