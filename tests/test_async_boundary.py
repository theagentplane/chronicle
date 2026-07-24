"""Async (`async def`) boundaries record like sync ones, isolate per request, and
capture failures. Tests drive coroutines with asyncio.run so no plugin is needed."""

from __future__ import annotations

import asyncio

import pytest

from chronicle import ReplayPlan, boundary, reset_session


@pytest.mark.layer1
def test_async_boundary_records_like_sync():
    @boundary("agent", kind="llm")
    async def agent(state: dict) -> dict:
        return {"completion": "ok", "finish_reason": "stop", "model": "gpt-4o", "temperature": 0.1}

    async def run():
        session = reset_session()
        session.begin_trace("t-async")
        out = await agent({"messages": [{"role": "user", "content": "hi"}]})
        return session, out

    session, out = asyncio.run(run())
    assert out["completion"] == "ok"
    env = session._recorded_envelopes[-1]
    assert env.boundary_kind == "llm"
    assert env.metadata.model_version == "gpt-4o"
    assert env.metadata.sampling_params.temperature == 0.1


@pytest.mark.layer1
def test_concurrent_async_traces_are_isolated():
    @boundary("node", kind="tool")
    async def node(tag: str) -> dict:
        await asyncio.sleep(0)  # yield so the two workers interleave
        return {"status": "ok", "tag": tag}

    async def worker(tag: str, out: dict) -> None:
        session = reset_session()
        session.begin_trace(f"trace-{tag}")
        await node(tag)
        await asyncio.sleep(0)
        await node(tag)
        out[tag] = session

    async def main():
        out: dict = {}
        await asyncio.gather(worker("a", out), worker("b", out))
        return out

    out = asyncio.run(main())
    sa, sb = out["a"], out["b"]
    assert sa is not sb
    assert len(sa._recorded_envelopes) == 2
    assert len(sb._recorded_envelopes) == 2
    # No cross-talk: each session only holds its own trace.
    assert all(e.trace_id == "trace-a" for e in sa._recorded_envelopes)
    assert all(e.trace_id == "trace-b" for e in sb._recorded_envelopes)


@pytest.mark.layer1
def test_async_failure_records_error_and_reraises():
    @boundary("boom", kind="tool")
    async def boom(x: int) -> dict:
        raise ValueError("nope")

    async def run():
        session = reset_session()
        session.begin_trace("t-err")
        with pytest.raises(ValueError, match="nope"):
            await boom(1)
        return session

    session = asyncio.run(run())
    env = session._recorded_envelopes[-1]
    assert env.action_result.error == "nope"
    assert env.action_result.error_type == "ValueError"
    assert env.action_result.finish_reason == "error"


@pytest.mark.layer1
def test_async_cutpoint_replay(tmp_path):
    @boundary("agent", kind="llm")
    async def agent(state: dict) -> dict:
        return {
            "completion": "delete it",
            "finish_reason": "tool_calls",
            "tool_calls": [{"name": "do", "arguments": {"v": 1}}],
        }

    @boundary("do", kind="tool")
    async def do_ungated(v: int) -> dict:
        return {"status": "did", "v": v}

    @boundary("do", kind="tool")
    async def do_gated(v: int) -> dict:
        return {"blocked": True}

    async def run_agent(do_fn):
        decision = await agent({"messages": []})
        args = decision["tool_calls"][0]["arguments"]
        await do_fn(args["v"])

    trace = tmp_path / "trace"

    async def record():
        session = reset_session()
        session.begin_trace("inc")
        await run_agent(do_ungated)
        session.export_trace(str(trace))

    asyncio.run(record())

    async def replay():
        session = reset_session()
        session.load_trace(str(trace))
        session.enable_replay(ReplayPlan().stub("agent", 1).live("do", 1))
        await run_agent(do_gated)  # gated version runs live at the cut-point
        return session

    session = asyncio.run(replay())
    assert session.captured_result("do", 1)["blocked"] is True
