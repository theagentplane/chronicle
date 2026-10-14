"""Errors the framework raises on purpose.

``AbortCall`` (a hook stopping a call) is in ``chronicle.framework.hooks``. These two belong to
replay: a recorded failure that a stub hands back, and a boundary that has no recording left.
"""


class RecordedCallError(Exception):
    """A stubbed boundary re-raises the failure that was recorded (issue #34).

    The original exception type cannot be rebuilt from a recording, so ``error_type`` carries its
    class name and the message is the recorded one.
    """

    def __init__(self, error_type: str, message: str, *, name: str, invocation_index: int) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.name = name
        self.invocation_index = invocation_index

    def __str__(self) -> str:
        return f"{self.error_type}: {super().__str__()}"


class ReplayMismatchError(LookupError):
    """Replay needs a recording that is not there.

    Matching is by boundary name plus call count (design section 7.4), so a fix that calls a
    boundary more often than the recorded run has no n-th recording to hand back.
    """
