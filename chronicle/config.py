"""Runtime configuration from the environment."""

from __future__ import annotations

import os

# Explicit falsy tokens. Unset means enabled (backward compatible).
_DISABLED = frozenset({"0", "false", "no", "off"})


def is_enabled() -> bool:
    """Whether Chronicle LIVE recording / instrumentation is active.

    Controlled by ``CHRONICLE_ENABLED`` (default on). Set to ``0``, ``false``,
    ``off``, or ``no`` to make ``@boundary``, ``wrap``, ``wrap_llm``,
    ``record()``, and ``EnvelopeRecorder`` no-ops for live runs so an agent can
    be timed with and without Chronicle. Replay is unaffected so cut-point
    fixtures keep working.
    """
    raw = os.environ.get("CHRONICLE_ENABLED")
    if raw is None:
        return True
    return raw.strip().lower() not in _DISABLED
