"""``@boundary`` and ``wrap_llm``: declare a decision point in user code (design 4.1, 8.1).

Both build one ``BoundarySpec`` at declaration time (so an unknown kind fails then) and send every
call through the process-wide interceptor, sync or ``async def``. The wrapper is transparent:
the caller gets exactly what the function returned, or the exception it raised after the failure
is recorded.

Streaming is not supported (design section 6.5). A generator or async generator function is
returned unwrapped, so it keeps working and is simply not recorded.

How arguments are named in ``input.raw`` is the rule in
``chronicle.framework.interceptor.argument_binding_utils``.
"""

import functools
import inspect
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from agentplane_primitives.enums import Kind
from pydantic import JsonValue

from chronicle.framework.adapters.adapter_registry import get_adapter
from chronicle.framework.adapters.adapter_types import LlmAdapter
from chronicle.framework.boundary_spec_types import BoundarySpec
from chronicle.framework.interceptor.argument_binding_utils import resolve_signature
from chronicle.framework.kinds.kind_registry import parse_kind
from chronicle.interfaces.runtime_utils import interceptor

F = TypeVar("F", bound=Callable[..., Any])


def make_spec(
    fn: Callable[..., Any],
    name: str,
    kind: str | Kind,
    *,
    provider: str | None = None,
    adapter: LlmAdapter | None = None,
    extract_input: Callable[..., Mapping[str, Any]] | None = None,
    extract_result: Callable[[Any], Any] | None = None,
    extract_metadata: Callable[[Any], Mapping[str, Any]] | None = None,
    metadata: Mapping[str, JsonValue] | None = None,
) -> BoundarySpec:
    """Build the spec for a boundary; raises ``ValueError`` for an unknown kind."""
    parsed = parse_kind(kind)
    chosen = None
    if parsed is Kind.LLM:
        chosen = adapter if adapter is not None else get_adapter(provider)
    return BoundarySpec(
        name=name,
        kind=parsed,
        adapter=chosen,
        extract_input=extract_input,
        extract_result=extract_result,
        extract_metadata=extract_metadata,
        metadata=dict(metadata or {}),
        signature=resolve_signature(fn),
    )


def bind_boundary(spec: BoundarySpec, fn: Callable[..., Any]) -> Callable[..., Any]:
    """Return ``fn`` wrapped so every call is a crossing of ``spec``."""
    if inspect.isgeneratorfunction(fn) or inspect.isasyncgenfunction(fn):
        return fn  # streaming is not supported: leave the function alone

    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            return await interceptor.acall(spec, fn, args, kwargs)

        return async_wrapper

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return interceptor.call(spec, fn, args, kwargs)

    return wrapper


def boundary(
    name: str,
    *,
    kind: str | Kind = Kind.TOOL,
    provider: str | None = None,
    adapter: LlmAdapter | None = None,
    extract_input: Callable[..., Mapping[str, Any]] | None = None,
    extract_result: Callable[[Any], Any] | None = None,
    extract_metadata: Callable[[Any], Mapping[str, Any]] | None = None,
) -> Callable[[F], F]:
    """Declare ``name`` as a boundary of ``kind`` (``"tool"`` or ``"llm"``).

    - ``kind="llm"`` boundaries use the adapter for ``provider`` (``"openai"``,
      ``"anthropic"``, ...) or an explicit ``adapter``. With neither, ``usage`` is ``null`` and
      ``provider`` is ``unknown``.
    - ``extract_input(*args, **kwargs)`` returns the arguments by name, instead of the default
      signature-bound capture.
    - ``extract_result(result)`` shapes what is recorded as ``output.raw``; the caller still
      receives the real result.
    - ``extract_metadata(result)`` adds envelope metadata derived from the result.

    Works on sync functions and ``async def`` coroutines.
    """

    def decorator(fn: F) -> F:
        spec = make_spec(
            fn,
            name,
            kind,
            provider=provider,
            adapter=adapter,
            extract_input=extract_input,
            extract_result=extract_result,
            extract_metadata=extract_metadata,
        )
        return bind_boundary(spec, fn)  # type: ignore[return-value]

    return decorator


def wrap_llm(
    name: str,
    dispatch: Callable[..., Any],
    *,
    provider: str | None = None,
    adapter: LlmAdapter | None = None,
    extract_input: Callable[..., Mapping[str, Any]] | None = None,
    extract_result: Callable[[Any], Any] | None = None,
    extract_metadata: Callable[[Any], Mapping[str, Any]] | None = None,
) -> Callable[..., Any]:
    """Wrap an LLM callable (``kind="llm"``) that is a dispatch function rather than a method.

    Same transparent record, stub and run contract as ``@boundary(name, kind="llm")``.
    """
    spec = make_spec(
        dispatch,
        name,
        Kind.LLM,
        provider=provider,
        adapter=adapter,
        extract_input=extract_input,
        extract_result=extract_result,
        extract_metadata=extract_metadata,
    )
    return bind_boundary(spec, dispatch)
