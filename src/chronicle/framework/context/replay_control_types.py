"""``ReplayControl``: what a REPLAY session asks of the replay capability (design section 7).

The interceptor lives in the framework layer and the replay plan and recording live in the
capabilities layer, so the interceptor sees replay only through this protocol.
"""

from typing import Any, Protocol

from agentplane_primitives.models import Envelope
from pydantic import JsonValue

from chronicle.framework.boundary_enums import BoundaryMode


class ReplayControl(Protocol):
    """Decides, per boundary and call count, whether to stub or run, and serves the recording."""

    def next_invocation(self, name: str) -> int:
        """Reserve and return the call number of this crossing of ``name`` (1 for the first).

        The cursor advances here, atomically, so it advances even if the call then raises and
        two parallel crossings never get the same number.
        """
        ...

    def mode_for(self, name: str, invocation_index: int) -> BoundaryMode:
        """STUB or RUN for the ``invocation_index``-th call of ``name``."""
        ...

    def take(self, name: str, invocation_index: int) -> Envelope:
        """Return the ``invocation_index``-th recorded envelope of ``name`` to stub with."""
        ...

    def capture(
        self,
        name: str,
        invocation_index: int,
        arguments: dict[str, JsonValue],
        result: Any,
    ) -> None:
        """Keep a RUN crossing's input and return value in memory for assertions."""
        ...
