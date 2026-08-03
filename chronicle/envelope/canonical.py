"""Canonical, volatile-insensitive hashing of recorded inputs.

The replay checksum hashes each crossing's recorded input. A faithful replay must not
raise merely because a volatile field (a timestamp, a generated identifier, an absolute
path) differs, so such fields are dropped before hashing. Dictionaries are key-sorted so
that field order does not affect the digest.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

# Field names dropped before hashing. Extend via canonicalize(..., volatile=...).
DEFAULT_VOLATILE: frozenset[str] = frozenset(
    {
        "timestamp",
        "created_at",
        "updated_at",
        "time",
        "date",
        "request_id",
        "span_id",
        "run_id",
        "uuid",
        "nonce",
    }
)


def canonicalize(value: Any, volatile: Iterable[str] = DEFAULT_VOLATILE) -> Any:
    """Return a copy of ``value`` with volatile dict keys dropped, recursively."""
    volatile = set(volatile)
    if isinstance(value, dict):
        return {k: canonicalize(v, volatile) for k, v in value.items() if k not in volatile}
    if isinstance(value, (list, tuple)):
        return [canonicalize(v, volatile) for v in value]
    return value


def digest(value: Any, volatile: Iterable[str] = DEFAULT_VOLATILE) -> str:
    """SHA-256 of the canonicalized value, with dict keys sorted for stability."""
    canonical = canonicalize(value, volatile)
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
