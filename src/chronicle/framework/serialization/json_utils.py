"""``to_json``: the JSON form of a boundary's input or output (design section 2.3).

``raw`` is the JSON form of the value as it crossed the boundary. Common cases convert
automatically (JSON-native values, pydantic models, dataclasses, mappings, sequences); anything
else is stored as its text ``repr``, which replay cannot restore. Making that loss visible is
future scope (design section 12.1, serialization hardening), so this converter only has to be
total: it never raises, so recording can never break the call.
"""

import dataclasses
import math
from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import JsonValue

_MAX_DEPTH = 12


def to_json(value: Any, _depth: int = 0) -> JsonValue:
    """Return ``value`` as JSON-compatible data. Never raises."""
    try:
        return _convert(value, _depth)
    except Exception:  # a hostile __repr__, a broken model_dump: the call must not break
        return "<unserializable>"


def _convert(value: Any, depth: int) -> JsonValue:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    if depth > _MAX_DEPTH:
        return repr(value)
    if isinstance(value, Enum):
        return _convert(value.value, depth + 1)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, UUID | Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _convert(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_convert(item, depth + 1) for item in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _convert(getattr(value, field.name), depth + 1)
            for field in dataclasses.fields(value)
        }
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _convert(model_dump(mode="json"), depth + 1)
    return repr(value)
