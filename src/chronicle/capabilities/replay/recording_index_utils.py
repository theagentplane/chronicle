"""Index a span's recorded envelopes by boundary name, in call order (design section 7.3).

Replay takes "the next recorded envelope for that boundary name". Call order is the span-local
``chronicle.invocation_index`` Chronicle wrote at record time; envelopes without it (written by
something else) fall back to start time.
"""

from collections.abc import Iterable

from agentplane_primitives.models import Envelope

INVOCATION_KEY = "chronicle.invocation_index"
SEQUENCE_KEY = "chronicle.sequence"


def _order(envelope: Envelope) -> tuple[int, float]:
    invocation = envelope.metadata.get(INVOCATION_KEY)
    started = envelope.envelope_status.started_at.timestamp()
    if isinstance(invocation, int) and not isinstance(invocation, bool):
        return (invocation, started)
    return (0, started)


def build_index(envelopes: Iterable[Envelope]) -> dict[str, list[Envelope]]:
    """Group closed envelopes by name, each group in call order."""
    index: dict[str, list[Envelope]] = {}
    for envelope in envelopes:
        index.setdefault(envelope.name, []).append(envelope)
    for group in index.values():
        group.sort(key=_order)
    return index
