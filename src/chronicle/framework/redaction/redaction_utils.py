"""Apply redactors to the JSON form of a record (design section 4.5).

Redaction acts on the JSON form: every string value, at any depth, is passed through the
redactors in order. Keys are left alone so the structure stays intact.
"""

from collections.abc import Sequence

from pydantic import JsonValue

from chronicle.framework.redaction.redactor_types import Redactor


def redact_json(value: JsonValue, redactors: Sequence[Redactor]) -> JsonValue:
    """Return ``value`` with every string value passed through ``redactors``."""
    if not redactors:
        return value
    return _scrub(value, redactors)


def _scrub(value: JsonValue, redactors: Sequence[Redactor]) -> JsonValue:
    if isinstance(value, str):
        for redactor in redactors:
            value = redactor(value)
        return value
    if isinstance(value, list):
        return [_scrub(item, redactors) for item in value]
    if isinstance(value, dict):
        return {key: _scrub(item, redactors) for key, item in value.items()}
    return value
