"""Layer 1: deterministic replay tests — no LLM API calls."""

from pathlib import Path

import pytest

from chronicle.envelope.schema import Envelope
from chronicle.replay import ReplayInjector, assert_no_llm_call, enable_replay_guard
from chronicle.replay.injector import LLMCallBlockedError, disable_replay_guard

FIXTURES = Path(__file__).parent.parent / "fixtures" / "envelopes"


@pytest.fixture
def sample_envelope() -> Envelope:
    return Envelope.from_file(str(FIXTURES / "support-agent-001.json"))


@pytest.mark.layer1
def test_replay_injects_recorded_state(sample_envelope: Envelope):
    injector = ReplayInjector(sample_envelope)
    state = injector.inject_state({})
    assert state["messages"][0]["content"] == "How do I reset my API key?"
    assert len(state["rag_chunks"]) == 1
    assert state["messages"][0]["role"] == "user"


@pytest.mark.layer1
def test_replay_stubs_llm_without_api(sample_envelope: Envelope):
    injector = ReplayInjector(sample_envelope)

    def agent(state, inj):
        result = inj.stub_llm()
        return {"completion": result.llm.text, "finish_reason": result.llm.finish_reason}

    _, ctx, assertions = injector.replay(agent)
    no_llm = next(a for a in assertions if a.name == "no_llm_calls")
    assert no_llm.passed


@pytest.mark.layer1
def test_replay_asserts_tool_calls(sample_envelope: Envelope):
    injector = ReplayInjector(sample_envelope)

    def agent(state, inj):
        inj.stub_llm()
        for tc in sample_envelope.output.llm.tool_calls:
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
        for tc in sample_envelope.output.llm.tool_calls:
            inj.stub_tool(tc.name, tc.arguments)
        return {
            "completion": sample_envelope.output.llm.text,
            "finish_reason": sample_envelope.output.llm.finish_reason,
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
        for tc in envelope.output.llm.tool_calls:
            inj.stub_tool(tc.name, tc.arguments)
        return {"finish_reason": envelope.output.llm.finish_reason}

    _, _, assertions = injector.replay(agent)
    assert all(a.passed for a in assertions)

@pytest.mark.layer1
def test_structural_assertions_cover_success_and_failure_paths(sample_envelope: Envelope):
    from chronicle.replay.assertions import StructuralAssertions

    assertions = StructuralAssertions(
        sample_envelope,
        required_result_keys=["answer"],
        forbid_tool_names=["delete_file"],
    )
    good_log = [{
        "type": "tool_stub",
        "name": "search_docs",
        "arguments": {"query": "api key", "limit": 3},
    }]

    assert assertions.assert_tools_called(good_log).passed
    assert assertions.assert_tool_argument_keys(good_log).passed
    assert assertions.assert_result_structure({"answer": "ok"}).passed
    assert assertions.assert_finish_reason({"finish_reason": "tool_calls"}).passed
    assert assertions.assert_no_llm_calls(good_log).passed

    missing_tool = assertions.assert_tools_called([])
    assert not missing_tool.passed
    assert "Missing tool calls" in missing_tool.message

    bad_args = assertions.assert_tool_argument_keys([
        {"type": "tool_stub", "name": "search_docs", "arguments": {}}
    ])
    assert not bad_args.passed
    assert "missing keys" in bad_args.message

    forbidden = assertions.assert_tools_called(good_log + [
        {"type": "tool_stub", "name": "delete_file", "arguments": {}}
    ])
    assert not forbidden.passed
    assert "Forbidden tools called" in forbidden.message

    bad_result = assertions.assert_result_structure({})
    assert not bad_result.passed
    assert "Missing result keys" in bad_result.message

    bad_finish = assertions.assert_finish_reason({"finish_reason": "stop"})
    assert not bad_finish.passed
    assert "Expected finish_reason" in bad_finish.message

    real_llm = assertions.assert_no_llm_calls([{"type": "llm_api_call"}])
    assert not real_llm.passed
    assert "real LLM API call" in real_llm.message
