"""Name the arguments of a call: the rule behind ``input.raw`` (design section 2.3).

``ToolInput.raw`` is an object by argument name, so every argument needs a key. The rule:

1. **Declared parameters keep their declared name**, positional-only ones included
   (``def f(a, /)`` gives ``{"a": ...}``). ``self`` and ``cls`` are skipped.
2. **``**kwargs`` is flattened**: each extra keyword argument becomes a top-level key.
3. **``*args`` keeps its declared name** and holds a list (``def f(*items)`` gives
   ``{"items": [...]}``).
4. **If the signature cannot be read** (some builtins and C callables) positional arguments are
   stored as a list under ``args`` and keyword arguments are top-level keys.

Capture never raises: on any failure the call is stored as ``{"args": [...], "kwargs": {...}}``.
"""

import inspect
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import JsonValue

from chronicle.framework.serialization.json_utils import to_json

_SKIPPED = ("self", "cls")


def resolve_signature(fn: Callable[..., Any]) -> inspect.Signature | None:
    """Return ``fn``'s signature, or ``None`` if it cannot be introspected."""
    try:
        return inspect.signature(fn)
    except (TypeError, ValueError):
        return None


def bind_arguments(
    signature: inspect.Signature | None, args: tuple[Any, ...], kwargs: Mapping[str, Any]
) -> dict[str, JsonValue]:
    """Return the JSON form of the call's arguments by name, following the rule above."""
    try:
        return _bind(signature, args, kwargs)
    except Exception:  # capture must never break the wrapped call
        return {"args": to_json(list(args)), "kwargs": to_json(dict(kwargs))}


def _bind(
    signature: inspect.Signature | None, args: tuple[Any, ...], kwargs: Mapping[str, Any]
) -> dict[str, JsonValue]:
    if signature is None:
        result: dict[str, JsonValue] = {"args": to_json(list(args))}
        result.update({str(key): to_json(value) for key, value in kwargs.items()})
        return result
    bound = signature.bind_partial(*args, **kwargs)
    result = {}
    for name, value in bound.arguments.items():
        if name in _SKIPPED:
            continue
        kind = signature.parameters[name].kind
        if kind is inspect.Parameter.VAR_KEYWORD:
            result.update({str(key): to_json(item) for key, item in value.items()})
        elif kind is inspect.Parameter.VAR_POSITIONAL:
            result[name] = to_json(list(value))
        else:
            result[name] = to_json(value)
    return result
