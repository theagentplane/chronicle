"""``RecordedDict`` and ``RecordedList``: what a stubbed boundary hands back (design 7.3).

Replay returns ``output.raw``, the JSON form of the recorded return value. It is wrapped so that
attribute access works the way it does on an SDK response (``resp.choices[0].message.content``),
while ``isinstance(x, dict)``, indexing and JSON conversion keep working. Rebuilding the original
Python type from ``raw`` is future scope (design section 12.1).
"""

from typing import Any


class RecordedDict(dict[str, Any]):
    """A dict whose keys are also readable as attributes."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None


class RecordedList(list[Any]):
    """A list that stands for a recorded JSON array."""
