"""What every topology must hold: propagation rules, transparency, failures, hooks, redaction."""

from typing import Any

import pytest
from agentplane_primitives.enums import Status
from agentplane_primitives.models import Envelope, LlmOutput, ToolOutput

import chronicle
from chronicle import AbortCall, CallInfo, FunctionHook
from chronicle.framework.hooks.hook_registry import default_hooks
from tests.e2e.agents.tool_types import Tool
from tests.e2e.assertions import (
    assert_well_formed_trace,
    envelopes,
    llm_envelopes,
    settle,
    span_of,
    tool_envelopes,
    trace_ids,
)
from tests.e2e.scripts import call_tool, delegate_then_answer, final
from tests.e2e.system import System, call_agent
from tests.support.fake_llm_server import ErrorResponse
from tests.support.in_memory_control_plane import invocation_index


def _pair(system: System, **orchestrator_kwargs: Any) -> tuple[Any, Any]:
    specialist = system.add("specialist", "handrolled", [final("handrolled", "specialist done")])
    orchestrator = system.add(
        "orchestrator",
        orchestrator_kwargs.pop("framework", "handrolled"),
        orchestrator_kwargs.pop(
            "script",
            delegate_then_answer("handrolled", "ask_specialist", "work", "all done"),
        ),
        tools=[specialist.peer_tool("ask_specialist"), *orchestrator_kwargs.pop("tools", [])],
        **orchestrator_kwargs,
    )
    return orchestrator, specialist


# ---- propagation ------------------------------------------------------------------------


def test_a_malformed_inbound_traceparent_mints_a_new_trace_and_never_raises(
    system: System,
) -> None:
    system.add("solo", "handrolled", [final("handrolled", "fine")])
    system.configure()

    response = call_agent(
        system.nodes["solo"].url, "hi", {"traceparent": "00-this-is-not-valid-01"}
    )

    assert response.status_code == 200
    assert_well_formed_trace(system, ["solo"])
    assert span_of(system, "solo").parent_envelope_id is None


def test_a_valid_inbound_traceparent_is_joined(system: System) -> None:
    system.add("solo", "handrolled", [final("handrolled", "fine")])
    system.configure()
    trace_id, caller_envelope = "ab" * 16, "cd" * 8

    call_agent(
        system.nodes["solo"].url, "hi", {"traceparent": f"00-{trace_id}-{caller_envelope}-01"}
    )

    span = span_of(system, "solo")
    assert span.trace_id == trace_id
    assert span.parent_envelope_id == caller_envelope


def test_propagation_is_default_deny(system: System) -> None:
    """With no ``inject_hosts`` the peer is never given the header, so it starts its own trace."""
    _pair(system)
    system.configure(inject_hosts=[])

    response = system.call("orchestrator", "go")

    assert response.json() == {"answer": "all done"}
    settle(system)
    assert len(trace_ids(system)) == 2  # two services, two traces: nothing was linked
    assert all(s.parent_envelope_id is None for s in system.plane.spans.values())
    # and the call was not recorded as a tool envelope either
    assert not [e for e in system.plane.envelopes.values() if e.name.startswith("http ")]


# ---- transparency ----------------------------------------------------------------------


def test_the_agents_see_the_same_results_with_chronicle_on_and_off() -> None:
    def run(enabled: bool) -> tuple[int, Any]:
        system = System()
        try:
            _pair(system)
            system.configure(enabled=enabled)
            response = system.call("orchestrator", "go")
            return response.status_code, response.json()
        finally:
            system.close()

    chronicle.reset()
    assert run(enabled=True) == run(enabled=False) == (200, {"answer": "all done"})


def test_a_failing_boundary_raises_the_same_exception_on_and_off() -> None:
    class Boom(RuntimeError):
        pass

    @chronicle.boundary("explode")
    def explode() -> None:
        raise Boom("same either way")

    for enabled in (True, False):
        chronicle.reset()
        chronicle.configure(enabled=enabled)
        with pytest.raises(Boom, match="same either way"):
            explode()
    chronicle.reset()


# ---- failures and retries -----------------------------------------------------------------


def test_a_tool_error_is_recorded_as_a_failure_and_reraised(system: System) -> None:
    async def broken(task: str) -> str:
        raise ValueError(f"cannot do {task}")

    orchestrator = system.add(
        "orchestrator",
        "handrolled",
        [call_tool("handrolled", "broken", {"task": "x"}), final("handrolled", "handled it")],
        tools=[Tool(name="broken", description="always fails", run=broken)],
    )
    system.configure()

    response = system.call("orchestrator", "go")

    assert response.json() == {"answer": "handled it"}  # the agent saw the real exception
    assert_well_formed_trace(system, ["orchestrator"])
    (failed,) = [e for e in tool_envelopes(system, "orchestrator") if e.name == "tool.broken"]
    assert failed.envelope_status.status is Status.FAILURE
    assert isinstance(failed.output, ToolOutput)
    assert failed.output.error is not None
    assert (failed.output.error.type, failed.output.error.message) == ("ValueError", "cannot do x")
    fed_back = orchestrator.llm.requests[1].body["messages"][-1]["content"]
    assert fed_back == "error: ValueError: cannot do x"


def test_an_llm_error_is_recorded_and_the_request_fails(system: System) -> None:
    system.add(
        "orchestrator",
        "openai_sdk",
        [ErrorResponse(429, {"error": {"message": "slow down", "type": "rate_limit_error"}})],
    )
    system.configure()

    response = system.call("orchestrator", "go")

    assert response.status_code == 500
    settle(system)
    (llm,) = llm_envelopes(system, "orchestrator")
    assert llm.envelope_status.status is Status.FAILURE
    assert isinstance(llm.output, LlmOutput)
    assert llm.output.error is not None
    assert llm.output.error.type == "RateLimitError"
    assert (llm.output.content, llm.output.usage) == ([], None)
    assert span_of(system, "orchestrator").status is Status.FAILURE


def test_a_declared_retry_links_with_retry_of(system: System) -> None:
    attempts = {"n": 0}
    seen: dict[str, Envelope] = {}

    class Capture(chronicle.Hook):
        def record(self, envelope: Envelope) -> None:
            seen[envelope.name] = envelope

    default_hooks.register(Capture())

    @chronicle.boundary("backend.call")
    async def backend(task: str) -> str:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ConnectionError("blip")
        return f"ok {task}"

    async def with_retry(task: str) -> str:
        try:
            return await backend(task)
        except ConnectionError:
            with chronicle.attempt(2, of=seen["backend.call"].envelope_id):
                return await backend(task)

    system.add(
        "orchestrator",
        "handrolled",
        [call_tool("handrolled", "robust", {"task": "x"}), final("handrolled", "retried fine")],
        tools=[Tool(name="robust", description="retries once", run=with_retry)],
    )
    system.configure()

    assert system.call("orchestrator", "go").json() == {"answer": "retried fine"}
    settle(system)
    first, second = [e for e in envelopes(system, "orchestrator") if e.name == "backend.call"]
    assert (first.attempt, second.attempt) == (1, 2)
    assert first.envelope_status.status is Status.FAILURE
    assert second.envelope_status.status is Status.SUCCESS
    assert [(link.type.value, link.envelope_id) for link in second.links] == [
        ("retry_of", first.envelope_id)
    ]


# ---- hooks ------------------------------------------------------------------------------


@pytest.mark.parametrize("fail_flag", [False, True])
def test_abort_call_stops_the_call_and_is_recorded(system: System, fail_flag: bool) -> None:
    _orchestrator, specialist = _pair(system)

    def governor(call: CallInfo) -> None:
        if call.name == "tool.ask_specialist":
            raise AbortCall("budget exhausted")

    default_hooks.register(FunctionHook(enter=governor))
    system.configure(hooks_fail_call_on_error=fail_flag)

    response = system.call("orchestrator", "go")

    assert response.status_code == 200  # the agent saw the abort and answered anyway
    settle(system)
    (aborted,) = [
        e for e in tool_envelopes(system, "orchestrator") if e.name == "tool.ask_specialist"
    ]
    assert aborted.envelope_status.status is Status.FAILURE
    assert isinstance(aborted.output, ToolOutput)
    assert aborted.output.error is not None
    assert aborted.output.error.type == "AbortCall"
    assert specialist.llm.requests == []  # the specialist was never called
    assert len(trace_ids(system)) == 1


# ---- redaction ----------------------------------------------------------------------------


def test_a_secret_in_a_prompt_never_reaches_the_control_plane(system: System) -> None:
    secret = "sk-" + "live1234567890abcdefgh"
    orchestrator, _specialist = _pair(
        system,
        script=delegate_then_answer("handrolled", "ask_specialist", f"use key {secret}", "done"),
    )
    system.configure(default_redactors=True)

    response = system.call("orchestrator", f"please call with {secret}")

    assert response.json() == {"answer": "done"}
    settle(system)
    assert any(secret in str(r.body) for r in orchestrator.llm.requests)  # the call itself is real
    assert system.plane.raw_bodies
    assert not [body for body in system.plane.raw_bodies if secret in body]


# ---- delivery ---------------------------------------------------------------------------


def test_control_plane_down_fail_open_the_agents_still_work(system: System) -> None:
    _pair(system)
    system.configure()
    system.plane.down = True

    response = system.call("orchestrator", "go")

    assert response.json() == {"answer": "all done"}
    chronicle.flush()
    assert system.plane.envelopes == {}


def test_control_plane_down_strict_the_request_fails(system: System) -> None:
    _pair(system)
    system.configure(registration_fail_open=False, fail_open=False)
    system.plane.down = True

    response = system.call("orchestrator", "go")

    assert response.status_code == 500


def test_the_queue_is_flushed_at_span_end(system: System) -> None:
    _pair(system)
    system.configure(batch_size=500, flush_interval=60)  # nothing would flush on its own

    system.call("orchestrator", "go")
    settle(system)

    assert {s.service for s in system.plane.spans.values()} == {"orchestrator", "specialist"}
    assert system.plane.envelopes


def test_the_queue_is_flushed_at_shutdown(system: System) -> None:
    system.add("solo", "handrolled", [final("handrolled", "x")])
    system.configure(batch_size=500, flush_interval=60)

    @chronicle.boundary("ambient.work")
    def work() -> int:
        return 7

    assert work() == 7  # no span is open: the process-wide ambient span records it
    assert system.plane.envelopes == {}  # still queued
    chronicle.shutdown()
    assert [e.name for e in system.plane.envelopes.values()] == ["ambient.work"]


# ---- concurrency ------------------------------------------------------------------------


def test_parallel_requests_do_not_mix_spans_or_counters(system: System) -> None:
    from concurrent.futures import ThreadPoolExecutor

    def respond(body: dict[str, Any]) -> Any:
        has_result = any(m.get("role") == "tool" for m in body["messages"])
        if has_result:
            return final("handrolled", "joined")
        return call_tool("handrolled", "ask_specialist", {"task": "work"})

    specialist = system.add(
        "specialist", "handrolled", [], responder=lambda b: final("handrolled", "s")
    )
    system.add(
        "orchestrator",
        "handrolled",
        [],
        responder=respond,
        tools=[specialist.peer_tool("ask_specialist")],
    )
    system.configure()

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda i: system.call("orchestrator", f"job {i}"), range(12)))

    assert all(r.json() == {"answer": "joined"} for r in responses)
    settle(system)
    assert len(trace_ids(system)) == 12
    for trace_id in trace_ids(system):
        orchestrator_span = system.plane.span_for(trace_id, "orchestrator")
        specialist_span = system.plane.span_for(trace_id, "specialist")
        mine = system.plane.envelopes_of(orchestrator_span)
        # exactly this request's crossings: two model calls, one tool, one outbound call
        assert sorted(e.name for e in mine) == [
            "http POST " + specialist.server.host + "/run",
            "llm.chat",
            "llm.chat",
            "tool.ask_specialist",
        ]
        indexes = sorted(invocation_index(e) for e in mine if e.name == "llm.chat")
        assert indexes == [1, 2]
        outbound = next(e for e in mine if e.name.startswith("http "))
        assert specialist_span.parent_envelope_id == outbound.envelope_id
