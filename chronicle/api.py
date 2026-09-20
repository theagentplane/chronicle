"""One-call context managers over the session for the common flows.

These add no new behavior. They collapse the setup boilerplate (reset the
session, attach a store, begin or load a trace, enable replay) into a single
``with`` block, and hand you the same ``ChronicleSession`` so anything the
lower-level API can do is still available.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from chronicle.config import is_enabled
from chronicle.envelope.backends import Store, open_store
from chronicle.replay.plan import ReplayPlan
from chronicle.session import ChronicleSession, reset_session


@contextmanager
def record(
    name: str | None = None,
    *,
    trace_id: str | None = None,
    store: Store | str | Path | None = None,
    model_version: str | None = None,
    build_id: str | None = None,
    redactors: list[Callable[[str], str]] | None = None,
    export: str | Path | None = None,
    retain_envelopes: bool = True,
    attributes: dict[str, str] | None = None,
) -> Iterator[ChronicleSession]:
    """Record a trace in one block.

    ``name`` is a human label for the trace (kept as the ``chronicle.trace.name`` attribute
    on every envelope). The trace id itself is an OpenTelemetry trace id (32
    lowercase hex chars): minted for you, or passed as ``trace_id=``.

    Replaces the reset_session / attach store / begin_trace boilerplate. On a
    clean exit, if ``export`` is given, the trace graph is written there so the
    incident is ready to commit as a fixture.

        with chronicle.record(
            "incident-001",  # name, a label; the trace id is minted (OTel format)
            store=".chronicle/runs/incident.jsonl",
            export="fixtures/traces/incident-001/",
            attributes={"session_id": "sess_abc", "user_id": "u1"},
        ) as session:
            run_agent(...)

    When ``CHRONICLE_ENABLED`` is off, this is a no-op: yields a fresh session
    with no store and does not export. Boundaries inside the block also skip
    LIVE recording.

    Set ``retain_envelopes=False`` when you only need the store write (skips the
    in-session list; ``export_trace`` will be empty).

    ``attributes`` are trace-level flat string attributes copied onto every recorded
    envelope (OTel-style resource/span attributes).
    """
    session = reset_session()
    if not is_enabled():
        yield session
        return
    if store is not None:
        # A Store instance (has append) is used directly; a path/URL string is routed
        # through open_store, so store="sqlite:///runs.db" or an http control-plane URL
        # both work as well as a plain ".jsonl" path.
        session.store = store if hasattr(store, "append") else open_store(store)
    if model_version is not None:
        session.model_version = model_version
    if build_id is not None:
        session.build_id = build_id
    if redactors is not None:
        session.redactors = redactors
    session.retain_envelopes = retain_envelopes
    session.begin_trace(name, trace_id=trace_id, attributes=attributes)
    try:
        yield session
    finally:
        # Buffered (and keep-open) stores must flush so a short run or remainder
        # batch is not left only in memory when the context exits.
        store_obj = session.store
        if store_obj is not None:
            flush = getattr(store_obj, "flush", None)
            if callable(flush):
                flush()
    # Export only on a clean exit, so a crash mid-run doesn't overwrite a fixture
    # with a partial trace. Call session.export_trace(...) yourself if you need it.
    if export is not None and retain_envelopes:
        session.export_trace(export)


@contextmanager
def replay_trace(
    trace: str | Path,
    plan: ReplayPlan | None = None,
) -> Iterator[ChronicleSession]:
    """Replay a recorded trace in one block.

    Replaces reset_session / load_trace / enable_replay. Pass a ``ReplayPlan`` to
    stub upstream boundaries and run one live at a cut-point; omit it to stub
    everything.

        with chronicle.replay_trace(
            "fixtures/traces/incident-001/",
            ReplayPlan().stub("agent", 1).live("delete_file", 1).live("agent", 2),
        ) as session:
            run_agent(...)
            assert session.captured_result("delete_file", 1)["blocked"] is True
    """
    session = reset_session()
    session.load_trace(trace)
    session.enable_replay(plan)
    yield session
