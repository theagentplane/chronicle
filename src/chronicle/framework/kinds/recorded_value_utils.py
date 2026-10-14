"""Turn a recorded JSON value into what a stubbed boundary returns (design section 7.3)."""

from typing import Any

from chronicle.framework.kinds.recorded_value_types import RecordedDict, RecordedList


def to_recorded(value: Any) -> Any:
    """Wrap objects and arrays so attribute access works; leave scalars as they are."""
    if isinstance(value, dict):
        return RecordedDict({key: to_recorded(item) for key, item in value.items()})
    if isinstance(value, list):
        return RecordedList(to_recorded(item) for item in value)
    return value
