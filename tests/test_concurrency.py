"""Concurrency: parallel requests and threads must not mix up spans or counters (design 4.6)."""

import asyncio
import threading

import chronicle
from tests.support.in_memory_control_plane import InMemoryControlPlane, invocation_index


def test_threads_keep_their_own_span_and_counters(control_plane: InMemoryControlPlane) -> None:
    @chronicle.boundary("work")
    def work(n: int) -> int:
        return n

    sessions: dict[int, str] = {}

    def run(n: int) -> None:
        with chronicle.record(f"req-{n}") as session:
            sessions[n] = session.span_id
            for _ in range(3):
                work(n)

    threads = [threading.Thread(target=run, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    chronicle.flush()

    envelopes = control_plane.envelopes_named("work")
    assert len(envelopes) == 24
    for n, span_id in sessions.items():
        mine = [e for e in envelopes if e.span_id == span_id]
        assert [e.input.raw["n"] for e in mine] == [n, n, n]
        assert sorted(invocation_index(e) for e in mine) == [1, 2, 3]


def test_async_requests_keep_their_own_span(control_plane: InMemoryControlPlane) -> None:
    @chronicle.boundary("fetch")
    async def fetch(n: int) -> int:
        await asyncio.sleep(0.001 * (5 - n))  # finish out of order on purpose
        return n

    async def request(n: int) -> str:
        async with chronicle.aspan() as session:
            await fetch(n)
            await fetch(n)
            return session.span_id

    async def main() -> list[str]:
        return list(await asyncio.gather(*(request(n) for n in range(5))))

    span_ids = asyncio.run(main())
    chronicle.flush()
    assert len(set(span_ids)) == 5
    for n, span_id in enumerate(span_ids):
        mine = [e for e in control_plane.envelopes_named("fetch") if e.span_id == span_id]
        assert [e.input.raw["n"] for e in mine] == [n, n]
        assert sorted(invocation_index(e) for e in mine) == [1, 2]
