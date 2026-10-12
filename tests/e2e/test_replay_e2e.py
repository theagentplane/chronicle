"""Replay across a real recording: fetch a span from the control plane over HTTP and replay it.

The recording is made by a multi-agent system running over sockets; the replay then runs the
orchestrator's own code in this process with the downstream calls stubbed (no LLM call and no
call to the specialist), or with one changed boundary run live (a cut-point).
"""

import asyncio
from typing import Any

import pytest

import chronicle
from chronicle import ReplayMismatchError, ReplayPlan
from chronicle.repositories import HttpControlPlaneClient
from tests.e2e.assertions import settle, span_of
from tests.e2e.scripts import delegate_then_answer, final
from tests.e2e.system import System


def _recorded_system(system: System) -> tuple[Any, Any, str, str]:
    specialist = system.add("specialist", "handrolled", [final("handrolled", "specialist done")])
    orchestrator = system.add(
        "orchestrator",
        "handrolled",
        delegate_then_answer("handrolled", "ask_specialist", "work", "all done"),
        tools=[specialist.peer_tool("ask_specialist")],
    )
    system.configure()
    assert system.call("orchestrator", "go").json() == {"answer": "all done"}
    settle(system)
    span = span_of(system, "orchestrator")
    return orchestrator, specialist, span.trace_id, span.span_id


def _client(system: System) -> HttpControlPlaneClient:
    return HttpControlPlaneClient(system.plane_server.url)


def test_stub_replay_returns_the_recorded_outputs_and_calls_nothing(system: System) -> None:
    orchestrator, specialist, trace_id, span_id = _recorded_system(system)
    llm_calls = len(orchestrator.llm.requests)
    peer_calls = len(specialist.llm.requests)

    with chronicle.replay_trace(trace_id, span_id, client=_client(system)) as run:
        answer = asyncio.run(orchestrator.agent.run("go"))

    assert answer == "all done"  # the outputs match the recording
    assert len(orchestrator.llm.requests) == llm_calls  # no live LLM call
    assert len(specialist.llm.requests) == peer_calls  # the downstream agent was not re-run
    assert run.invocation_count("llm.chat") == 2
    assert run.invocation_count("tool.ask_specialist") == 1


def test_cut_point_runs_one_changed_boundary_live_and_stubs_the_rest(system: System) -> None:
    orchestrator, specialist, trace_id, span_id = _recorded_system(system)
    peer_calls = len(specialist.llm.requests)

    plan = ReplayPlan().run("tool.ask_specialist", 1)
    with chronicle.replay_trace(trace_id, span_id, plan, client=_client(system)) as run:
        answer = asyncio.run(orchestrator.agent.run("go"))

    assert answer == "all done"
    # the tool boundary ran real code (captured), but its own HTTP call is a stubbed boundary
    assert run.captured_input("tool.ask_specialist", 1) == {"task": "work"}
    assert run.captured_result("tool.ask_specialist", 1) == "specialist done"
    assert len(specialist.llm.requests) == peer_calls


def test_matching_is_by_name_plus_call_count(system: System) -> None:
    orchestrator, _specialist, trace_id, span_id = _recorded_system(system)

    async def run_twice() -> None:
        await orchestrator.agent.run("go")
        await orchestrator.agent.run("go again")  # a third and fourth model call: not recorded

    with (
        chronicle.replay_trace(trace_id, span_id, client=_client(system)),
        pytest.raises(ReplayMismatchError, match=r"llm\.chat"),
    ):
        asyncio.run(run_twice())


def test_a_span_is_replayed_on_its_own(system: System) -> None:
    """The downstream span is a separate replay unit (design section 7.1)."""
    _orchestrator, specialist, trace_id, _ = _recorded_system(system)
    span_id = span_of(system, "specialist").span_id

    with chronicle.replay_trace(trace_id, span_id, client=_client(system)) as run:
        answer = asyncio.run(specialist.agent.run("anything"))

    assert answer == "specialist done"
    assert run.invocation_count("llm.chat") == 1
