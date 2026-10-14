"""Cap the size of a payload before it is sent (design section 9, ``max_payload_bytes``).

The cap applies to every string value: a longer string is cut and a marker is appended, so the
structure of the payload stays intact and valid. The envelope is marked with the metadata key
``chronicle.truncated`` when anything was cut.
"""

from pydantic import JsonValue

TRUNCATION_MARKER = "...[truncated]"


def truncate_json(value: JsonValue, max_bytes: int | None) -> tuple[JsonValue, bool]:
    """Return ``value`` with long strings cut, and whether anything was cut."""
    if max_bytes is None:
        return value, False
    truncated = False

    def walk(item: JsonValue) -> JsonValue:
        nonlocal truncated
        if isinstance(item, str):
            encoded = item.encode("utf-8")
            if len(encoded) > max_bytes:
                truncated = True
                cut = encoded[:max_bytes].decode("utf-8", errors="ignore")
                return cut + TRUNCATION_MARKER
            return item
        if isinstance(item, list):
            return [walk(child) for child in item]
        if isinstance(item, dict):
            return {key: walk(child) for key, child in item.items()}
        return item

    result = walk(value)
    return result, truncated
