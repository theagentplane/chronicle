"""``attempt``: declare that the enclosed calls are a retry (design section 2.5).

Chronicle cannot know that a second call is a retry, and does not guess. A retry inside a
provider SDK (for example ``max_retries``) is invisible: one crossing. An application-level retry
loop declares itself:

    with chronicle.attempt(2, of=first_envelope_id):
        call_the_model()

Envelopes recorded inside the block carry ``attempt = 2`` and a ``retry_of`` link to ``of``.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from chronicle.framework.context.context_vars import attempt_var


@contextmanager
def attempt(number: int, *, of: str | None = None) -> Iterator[None]:
    """Mark envelopes recorded in the block as attempt ``number``, a retry of envelope ``of``."""
    if number < 1:
        raise ValueError("attempt number starts at 1")
    token = attempt_var.set((number, of))
    try:
        yield
    finally:
        attempt_var.reset(token)
