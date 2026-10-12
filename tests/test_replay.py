"""Replay: scoped to a span; STUB returns raw, RUN executes real code (design section 7)."""

import pytest

import chronicle
from chronicle import RecordedCallError, ReplayMismatchError, ReplayPlan
from tests.support.in_memory_control_plane import InMemoryControlPlane

calls: list[str] = []


@chronicle.boundary("search")
def search(query: str) -> dict[str, object]:
    calls.append(f"search:{query}")
    return {"hits": [{"title": "a"}, {"title": "b"}], "query": query}


@chronicle.boundary("delete_file")
def delete_file(path: str, max_amount: int = 10) -> dict[str, object]:
    calls.append(f"delete:{path}")
    return {"deleted": path, "blocked": False}


@chronicle.boundary("flaky")
def flaky() -> str:
    calls.append("flaky")
    raise ConnectionError("upstream down")


def agent() -> dict[str, object]:
    found = search("cats")
    first = found["hits"][0]["title"]  # type: ignore[index]
    return {"first": first, "delete": delete_file(f"/tmp/{first}")}


@pytest.fixture(autouse=True)
def _clear_calls() -> None:
    calls.clear()


def _record_incident(plane: InMemoryControlPlane) -> tuple[str, str]:
    with chronicle.record("incident") as session:
        agent()
    chronicle.flush()
    calls.clear()
    return session.trace_id, session.span_id


def test_stub_everything_makes_no_real_calls(control_plane: InMemoryControlPlane) -> None:
    trace_id, span_id = _record_incident(control_plane)
    with chronicle.replay_trace(trace_id, span_id, client=control_plane) as run:
        result = agent()
    assert calls == []
    assert result == {"first": "a", "delete": {"deleted": "/tmp/a", "blocked": False}}
    assert run.invocation_count("search") == 1


def test_stub_returns_attribute_access_over_recorded_json(
    control_plane: InMemoryControlPlane,
) -> None:
    trace_id, span_id = _record_incident(control_plane)
    with chronicle.replay_trace(trace_id, span_id, client=control_plane):
        found = search("anything")
    assert found.hits[1].title == "b"  # type: ignore[attr-defined]
    assert isinstance(found, dict)


def test_cut_point_runs_one_boundary_live(control_plane: InMemoryControlPlane) -> None:
    trace_id, span_id = _record_incident(control_plane)
    plan = ReplayPlan().run("delete_file", 1)
    with chronicle.replay_trace(trace_id, span_id, plan, client=control_plane) as run:
        agent()
    assert calls == ["delete:/tmp/a"]  # only the cut-point ran
    assert run.captured_input("delete_file", 1) == {"path": "/tmp/a"}
    assert run.captured_result("delete_file", 1) == {"deleted": "/tmp/a", "blocked": False}


def test_nothing_is_written_during_replay(control_plane: InMemoryControlPlane) -> None:
    trace_id, span_id = _record_incident(control_plane)
    before = (len(control_plane.envelopes), len(control_plane.spans))
    with chronicle.replay_trace(
        trace_id, span_id, ReplayPlan().run("search"), client=control_plane
    ):
        agent()
    chronicle.flush()
    assert (len(control_plane.envelopes), len(control_plane.spans)) == before


def test_matching_is_by_name_and_call_count(control_plane: InMemoryControlPlane) -> None:
    trace_id, span_id = _record_incident(control_plane)
    with chronicle.replay_trace(trace_id, span_id, client=control_plane):
        search("one")  # first recorded call
        with pytest.raises(ReplayMismatchError, match="only 1 call"):
            search("two")  # a second call has no recording


def test_a_recorded_failure_is_reraised_by_the_stub(control_plane: InMemoryControlPlane) -> None:
    with pytest.raises(ConnectionError), chronicle.record("incident") as session:
        flaky()
    chronicle.flush()
    calls.clear()
    with (
        chronicle.replay_trace(session.trace_id, session.span_id, client=control_plane),
        pytest.raises(RecordedCallError) as info,
    ):
        flaky()
    assert info.value.error_type == "ConnectionError"
    assert "upstream down" in str(info.value)
    assert calls == []


def test_run_advances_the_cursor_even_if_the_call_raises(
    control_plane: InMemoryControlPlane,
) -> None:
    with pytest.raises(ConnectionError), chronicle.record("incident") as session:
        flaky()
    chronicle.flush()
    plan = ReplayPlan().run("flaky", 1)
    with (
        chronicle.replay_trace(
            session.trace_id, session.span_id, plan, client=control_plane
        ) as run,
        pytest.raises(ConnectionError),
    ):
        flaky()
    assert run.invocation_count("flaky") == 1
