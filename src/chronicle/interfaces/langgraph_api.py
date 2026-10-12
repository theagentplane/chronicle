"""LangGraph instrumentation: every node and routing decision becomes a boundary (design 4.1).

    app = chronicle.instrument(graph).compile()

``instrument`` wraps every node in place, and every ``add_conditional_edges`` routing function,
before or after ``.compile()``. A node is a ``tool`` boundary by default; pass ``kind="llm"`` for
nodes that are model calls. Routing functions are ``tool`` boundaries too (the ``router`` kind is
retired): *which branch was taken* is recorded and replays deterministically.

Only the public ``StateGraph`` builder attributes (``nodes``, ``branches``) are touched, never
LangGraph's compiled internals, and ``langgraph`` is not imported here (duck typing), so the base
install does not need it. Idempotent: instrumenting the same graph twice wraps each node once.
"""

import asyncio
import contextvars
import functools
from collections.abc import Callable, Mapping
from typing import Any

from agentplane_primitives.enums import Kind

from chronicle.interfaces.boundary_api import boundary


def instrument_langgraph(
    nodes: Mapping[str, Callable[..., Any]], *, kind: str | Kind = Kind.TOOL
) -> dict[str, Callable[..., Any]]:
    """Wrap every node function of a plain mapping as a boundary."""
    return {name: boundary(name, kind=kind)(fn) for name, fn in nodes.items()}


def instrument(graph: Any, *, kind: str | Kind = Kind.TOOL) -> Any:
    """Instrument every node and conditional-edge router of a ``StateGraph`` (or compiled app)."""
    builder = getattr(graph, "builder", graph)
    for node_id, spec in getattr(builder, "nodes", {}).items():
        runnable = getattr(spec, "runnable", None)
        if runnable is not None:
            _instrument_runnable(runnable, node_id, kind)
    for source, branches in getattr(builder, "branches", {}).items():
        for name, branch_spec in branches.items():
            path = getattr(branch_spec, "path", None)
            if path is not None:
                _instrument_runnable(path, f"{source}:{name}", Kind.TOOL)
    return graph


def _instrument_runnable(runnable: Any, name: str, kind: str | Kind) -> None:
    """Wrap a ``RunnableCallable``'s underlying function(s) in place so both invoke and ainvoke
    record.

    A sync-only node gets an auto-generated ``afunc``: a ``functools.partial`` that runs ``func``
    in a thread executor. Rewiring ``func`` alone would leave that partial pointing at the
    original function and skip the boundary under ``ainvoke``, so the shim is rebuilt around the
    wrapped function.
    """
    if getattr(runnable, "_chronicle_instrumented", False):
        return
    func = getattr(runnable, "func", None)
    afunc = getattr(runnable, "afunc", None)
    if func is not None:
        wrapped_sync = boundary(name, kind=kind)(func)
        runnable.func = wrapped_sync
        if isinstance(afunc, functools.partial):
            runnable.afunc = _executor_shim(wrapped_sync)
        elif afunc is not None:
            runnable.afunc = boundary(name, kind=kind)(afunc)
    elif afunc is not None:
        runnable.afunc = boundary(name, kind=kind)(afunc)
    runnable._chronicle_instrumented = True


def _executor_shim(sync_fn: Callable[..., Any]) -> Callable[..., Any]:
    """Run an instrumented sync function in the default executor, keeping the context.

    The executor thread does not inherit this task's context variables (that is how the active
    session is scoped), so the context is copied and run inside the worker thread.
    """

    async def _call(*args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_running_loop()
        ctx = contextvars.copy_context()
        return await loop.run_in_executor(
            None, ctx.run, functools.partial(sync_fn, *args, **kwargs)
        )

    return _call
