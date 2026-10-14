"""Small helpers for reading loosely shaped JSON without raising (used by the adapters)."""

from typing import Any

from pydantic import JsonValue


def as_dict(value: Any) -> dict[str, JsonValue]:
    """Return ``value`` if it is an object, else an empty one."""
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[JsonValue]:
    """Return ``value`` if it is an array, else an empty one."""
    return value if isinstance(value, list) else []


def as_str(value: Any) -> str | None:
    """Return ``value`` if it is a non-empty string, else ``None``."""
    return value if isinstance(value, str) and value else None


def as_int(value: Any) -> int:
    """Return ``value`` as a non-negative integer, or 0 if it is not one."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float) and value.is_integer():
        return max(int(value), 0)
    return 0
