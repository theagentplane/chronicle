"""``chronicle.current_session``: read the active span without creating one (ADR 0010)."""

import asyncio

import chronicle
from tests.support.in_memory_control_plane import InMemoryControlPlane


def test_none_outside_any_span(control_plane: InMemoryControlPlane) -> None:
    assert chronicle.current_session() is None
    assert control_plane.spans == {}


def test_returns_the_session_inside_record(control_plane: InMemoryControlPlane) -> None:
    with chronicle.record("job") as session:
        active = chronicle.current_session()
        assert active is session
        assert active.trace_id == session.trace_id
        assert active.span_id == session.span_id
        assert active.parent_envelope_id is None
    assert chronicle.current_session() is None


def test_returns_the_session_inside_span(control_plane: InMemoryControlPlane) -> None:
    with chronicle.span() as session:
        assert chronicle.current_session() is session
    assert chronicle.current_session() is None


def test_nested_spans_return_the_inner_one_and_restore_the_outer(
    control_plane: InMemoryControlPlane,
) -> None:
    with chronicle.record("outer") as outer:
        with chronicle.span() as inner:
            assert inner is not outer
            assert chronicle.current_session() is inner
        assert chronicle.current_session() is outer
    assert chronicle.current_session() is None


def test_works_under_asyncio(control_plane: InMemoryControlPlane) -> None:
    async def request() -> str:
        assert chronicle.current_session() is None
        async with chronicle.aspan() as session:
            await asyncio.sleep(0)
            assert chronicle.current_session() is session
            return session.span_id

    async def main() -> list[str]:
        return list(await asyncio.gather(*(request() for _ in range(3))))

    span_ids = asyncio.run(main())
    assert len(set(span_ids)) == 3
    assert chronicle.current_session() is None


def test_does_not_create_an_ambient_session(control_plane: InMemoryControlPlane) -> None:
    @chronicle.boundary("noop")
    def noop() -> None:
        return None

    noop()  # a boundary outside a span runs on the implicit ambient session
    assert chronicle.current_session() is None
