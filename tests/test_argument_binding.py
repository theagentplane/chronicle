"""The rule that names arguments in ``input.raw`` (design section 2.3)."""

import inspect
from typing import Any

from chronicle.framework.interceptor.argument_binding_utils import bind_arguments, resolve_signature
from chronicle.framework.serialization import to_json


def _bind(fn: Any, *args: Any, **kwargs: Any) -> Any:
    return bind_arguments(resolve_signature(fn), args, kwargs)


def test_declared_parameters_keep_their_names() -> None:
    def f(a: int, b: int = 0) -> None: ...

    assert _bind(f, 1, b=2) == {"a": 1, "b": 2}


def test_positional_only_parameters_keep_their_names() -> None:
    def f(a: int, /, b: int) -> None: ...

    assert _bind(f, 1, 2) == {"a": 1, "b": 2}


def test_var_keyword_is_flattened_and_var_positional_keeps_its_name() -> None:
    def f(first: int, *items: int, **options: int) -> None: ...

    assert _bind(f, 1, 2, 3, x=9) == {"first": 1, "items": [2, 3], "x": 9}


def test_self_and_cls_are_skipped() -> None:
    class C:
        def method(self, value: int) -> None: ...

    assert bind_arguments(inspect.signature(C.method), (C(), 5), {}) == {"value": 5}


def test_without_a_signature_positional_arguments_go_under_args() -> None:
    assert bind_arguments(None, (1, 2), {"k": 3}) == {"args": [1, 2], "k": 3}


def test_a_call_that_does_not_bind_falls_back_to_args_and_kwargs() -> None:
    def f(a: int) -> None: ...

    assert _bind(f, 1, 2, 3) == {"args": [1, 2, 3], "kwargs": {}}


def test_to_json_is_total() -> None:
    class Hostile:
        def __repr__(self) -> str:
            raise RuntimeError("no repr")

    converted = to_json({"a": (1, 2), "b": {3}, "n": float("nan")})
    assert isinstance(converted, dict)
    assert converted["n"] == "nan"
    assert to_json(Hostile()) == "<unserializable>"
