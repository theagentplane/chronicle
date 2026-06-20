"""Layer 1: deterministic replay tests — no LLM API calls."""

from pathlib import Path

import pytest

from chronicle.envelope.schema import Envelope
from chronicle.replay import ReplayInjector, assert_no_llm_call, enable_replay_guard
from chronicle.replay.injector import LLMCallBlockedError, disable_replay_guard

FIXTURES = Path(__file__).parent.parent / "fixtures" / "envelopes"


@pytest.fixture
def sample_envelope() -> Envelope:
    return Envelope.from_file(str(FIXTURES / "incident-2026-06-17-001.json"))


@pytest.mark.layer1
def test_replay_injects_recorded_state(sample_envelope: Envelope):
    injector = ReplayInjector(sample_envelope)
    state = injector.inject_state({})
    assert state["messages"][0]["content"] == "How do I reset my API key?"
    assert len(state["rag_chunks"]) == 1


@pytest.mark.layer1
def test_replay_stubs_llm_without_api(sample_envelope: Envelope):
    injector = ReplayInjector(sample_envelope)

    def agent(state, inj):
        result = inj.stub_llm()
        return {"completion": result.completion, "finish_reason": result.finish_reason}

    _, ctx, assertions = injector.replay(agent)
    no_llm = next(a for a in assertions if a.name == "no_llm_calls")
    assert no_llm.passed


@pytest.mark.layer1
def test_replay_asserts_tool_calls(sample_envelope: Envelope):
    injector = ReplayInjector(sample_envelope)

    def agent(state, inj):
        inj.stub_llm()
        for tc in sample_envelope.action_result.tool_calls:
            inj.stub_tool(tc.name, tc.arguments)
        return {"finish_reason": "tool_calls"}

    _, _, assertions = injector.replay(agent)
    tools_assertion = next(a for a in assertions if a.name == "tools_called")
    assert tools_assertion.passed


@pytest.mark.layer1
def test_llm_call_blocked_in_replay_mode():
    enable_replay_guard()
    try:
        with pytest.raises(LLMCallBlockedError):
            assert_no_llm_call()
    finally:
        disable_replay_guard()


@pytest.mark.layer1
def test_fixture_regression_suite(sample_envelope: Envelope):
    """Every committed envelope fixture must pass Layer 1 structural replay."""
    injector = ReplayInjector(sample_envelope)

    def replay_agent(state, inj):
        inj.stub_llm()
        for tc in sample_envelope.action_result.tool_calls:
            inj.stub_tool(tc.name, tc.arguments)
        return {
            "completion": sample_envelope.action_result.completion,
            "finish_reason": sample_envelope.action_result.finish_reason,
        }

    _, _, assertions = injector.replay(replay_agent)
    assert all(a.passed for a in assertions), [
        f"{a.name}: {a.message}" for a in assertions if not a.passed
    ]


@pytest.mark.layer1
@pytest.mark.parametrize(
    "fixture_path",
    sorted((Path(__file__).parent.parent / "fixtures" / "envelopes").glob("*.json")),
    ids=lambda p: p.name,
)
def test_all_fixtures_pass_layer1(fixture_path: Path):
    envelope = Envelope.from_file(str(fixture_path))
    injector = ReplayInjector(envelope)

    def agent(state, inj):
        inj.stub_llm()
        for tc in envelope.action_result.tool_calls:
            inj.stub_tool(tc.name, tc.arguments)
        return {"finish_reason": envelope.action_result.finish_reason}

    _, _, assertions = injector.replay(agent)
    assert all(a.passed for a in assertions)
