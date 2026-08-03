"""Order-sensitive checksum over the crossings a replay stubs.

Two guards use it. (1) Fixture integrity: at record time a digest of the ordered
crossings is stored with the trace; loading a trace recomputes it and raises if a
committed fixture was edited in a way that changes a recorded input (volatile fields are
normalized first, so a timestamp edit does not false-fire). (2) Replay order: during
replay, ``ReplayVerifier`` checks that the crossings actually stubbed, in request order,
match the recorded subsequence the plan stubs, so an insertion, removal, or reordering
raises before a stub returns a value recorded for a different crossing.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from chronicle.envelope.canonical import digest
from chronicle.envelope.schema import Envelope


class ChecksumMismatch(RuntimeError):
    """Replay or a fixture diverged from the recorded crossings."""


def crossing_key(envelope: Envelope) -> str:
    """A stable identity for one recorded crossing: boundary, index, canonical input."""
    input_data = envelope.input_state.model_dump()
    return f"{envelope.node_id}#{envelope.invocation_index}:{digest(input_data)}"


def trace_checksum(envelopes: list[Envelope]) -> str:
    """Order-sensitive digest over the crossings in recorded (sequence) order."""
    hasher = hashlib.sha256()
    for envelope in sorted(envelopes, key=lambda e: e.sequence):
        hasher.update(crossing_key(envelope).encode("utf-8"))
        hasher.update(b"|")
    return hasher.hexdigest()


@dataclass(frozen=True)
class _Expected:
    boundary_id: str
    invocation_index: int
    key: str


class ReplayVerifier:
    """Checks stubbed crossings against the recorded stubbed subsequence, in order."""

    def __init__(self, expected: list[_Expected]) -> None:
        self._expected = expected
        self._pos = 0

    def check(self, boundary_id: str, invocation_index: int, envelope: Envelope) -> None:
        if self._pos >= len(self._expected):
            raise ChecksumMismatch(
                f"replay stubbed an extra crossing {boundary_id}@{invocation_index} "
                "beyond the recorded stubbed subsequence"
            )
        expected = self._expected[self._pos]
        if (boundary_id, invocation_index) != (expected.boundary_id, expected.invocation_index):
            raise ChecksumMismatch(
                f"stubbed crossing out of order: replay reached {boundary_id}@"
                f"{invocation_index} where the record has {expected.boundary_id}@"
                f"{expected.invocation_index}"
            )
        if crossing_key(envelope) != expected.key:
            raise ChecksumMismatch(
                f"stubbed crossing {boundary_id}@{invocation_index} does not match "
                "its recorded input"
            )
        self._pos += 1


def build_verifier(
    envelopes: list[Envelope],
    should_stub: Callable[[str, int], bool],
) -> ReplayVerifier:
    """The expected stubbed subsequence: recorded crossings the plan stubs, in order."""
    expected = [
        _Expected(env.node_id, env.invocation_index, crossing_key(env))
        for env in sorted(envelopes, key=lambda e: e.sequence)
        if should_stub(env.node_id, env.invocation_index)
    ]
    return ReplayVerifier(expected)
