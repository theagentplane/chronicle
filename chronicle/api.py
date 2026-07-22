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

from chronicle.envelope.store import EnvelopeStore
from chronicle.replay.plan import ReplayPlan
from chronicle.session import ChronicleSession, reset_session


@contextmanager
def record(
    trace_id: str | None = None,
    *,
    store: EnvelopeStore | str | Path | None = None,
    model_version: str | None = None,
    build_id: str | None = None,
    redactors: list[Callable[[str], str]] | None = None,
    export: str | Path | None = None,
) -> Iterator[ChronicleSession]:
    """Record a run in one block.

    Replaces the reset_session / attach store / begin_trace boilerplate. On a
    clean exit, if ``export`` is given, the trace graph is written there so the
    incident is ready to commit as a fixture.

        with chronicle.record(
            "incident-001",
            store=".chronicle/runs/incident.jsonl",
            export="fixtures/traces/incident-001/",
        ) as session:
            run_agent(...)
    """
    session = reset_session()
    if store is not None:
        session.store = store if isinstance(store, EnvelopeStore) else EnvelopeStore(store)
    if model_version is not None:
        session.model_version = model_version
    if build_id is not None:
        session.build_id = build_id
    if redactors is not None:
        session.redactors = redactors
    session.begin_trace(trace_id)
    yield session
    # Export only on a clean exit, so a crash mid-run doesn't overwrite a fixture
    # with a partial trace. Call session.export_trace(...) yourself if you need it.
    if export is not None:
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
