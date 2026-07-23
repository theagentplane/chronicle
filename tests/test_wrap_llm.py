"""Unit tests for wrap_llm — Chronicle-owned LLM tracing."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chronicle.boundary import wrap_llm
from chronicle.envelope.schema import InputState
from chronicle.replay.plan import ReplayPlan
from chronicle.session import reset_session


def _complete(provider: str, model: str, messages: list, **kwargs) -> dict:
    return {
        "completion": f"{provider}/{model}:{len(messages)}",
        "finish_reason": "stop",
        "model": model,
        "temperature": kwargs.get("temperature", 0.0),
        "usage": {"input_tokens": 3, "output_tokens": 2},
    }


@pytest.mark.layer1
def test_wrap_llm_records_envelope_kind_llm():
    session = reset_session()
    session.enable_live()
    session.begin_trace("wrap-llm-record")

    traced = wrap_llm("agent.chat", _complete)
    out = traced(
        "openai",
        "gpt-4o-mini",
        [{"role": "user", "content": "hi"}],
        temperature=0.2,
    )

    assert out["completion"] == "openai/gpt-4o-mini:1"
    assert len(session._recorded_envelopes) == 1
    env = session._recorded_envelopes[0]
    assert env.boundary_kind == "llm"
    assert env.node_id == "agent.chat"
    assert env.metadata.model_version == "gpt-4o-mini"
    assert env.metadata.sampling_params.temperature == 0.2
    assert env.input_state.messages == [{"role": "user", "content": "hi"}]
    assert env.input_state.graph_state["provider"] == "openai"
    assert env.input_state.graph_state["model"] == "gpt-4o-mini"


@pytest.mark.layer1
def test_wrap_llm_invokes_on_crossing_with_kind_llm():
    session = reset_session()
    session.enable_live()
    crossings: list[tuple] = []

    def hook(boundary_id, kind, input_state, result):
        crossings.append((boundary_id, kind, input_state, result))

    session.on_crossing = hook
    traced = wrap_llm("planner.chat", _complete)

    out = traced("openai", "gpt-4o-mini", [{"role": "user", "content": "plan"}])
    assert out["finish_reason"] == "stop"
    assert len(crossings) == 1
    bid, kind, inp, result = crossings[0]
    assert bid == "planner.chat"
    assert kind == "llm"
    assert isinstance(inp, InputState)
    assert inp.messages[0]["content"] == "plan"
    assert result == out


@pytest.mark.layer1
def test_wrap_llm_messages_only_signature():
    session = reset_session()
    session.enable_live()
    crossings: list[tuple] = []
    session.on_crossing = lambda *a: crossings.append(a)

    def complete(messages, **kwargs):
        return {"completion": messages[-1]["content"], "finish_reason": "stop"}

    traced = wrap_llm("simple.chat", complete)
    out = traced([{"role": "user", "content": "hello"}])

    assert out["completion"] == "hello"
    assert len(session._recorded_envelopes) == 1
    assert session._recorded_envelopes[0].boundary_kind == "llm"
    assert crossings[0][1] == "llm"
    assert crossings[0][2].messages[0]["content"] == "hello"


@pytest.mark.layer1
def test_wrap_llm_stub_replay_skips_dispatch_and_on_crossing(tmp_path):
    session = reset_session()
    session.enable_live()
    traced = wrap_llm("agent.chat", _complete)
    traced("openai", "gpt-4o-mini", [{"role": "user", "content": "fixture"}])
    trace_dir = tmp_path / "trace"
    session.export_trace(trace_dir)

    calls: list[tuple] = []

    def counting_dispatch(provider, model, messages, **kwargs):
        calls.append((provider, model, messages))
        return _complete(provider, model, messages, **kwargs)

    session = reset_session()
    session.load_trace(trace_dir)
    session.enable_replay(ReplayPlan().stub("agent.chat", 1))
    crossings: list[tuple] = []
    session.on_crossing = lambda *args: crossings.append(args)

    traced = wrap_llm("agent.chat", counting_dispatch)
    out = traced("openai", "gpt-4o-mini", [{"role": "user", "content": "ignored"}])

    assert out["completion"] == "openai/gpt-4o-mini:1"  # from fixture
    assert calls == []
    assert crossings == []


@pytest.mark.layer1
def test_wrap_llm_live_cutpoint_fires_on_crossing(tmp_path):
    session = reset_session()
    session.enable_live()
    traced = wrap_llm("agent.chat", _complete)
    traced("openai", "gpt-4o-mini", [{"role": "user", "content": "fixture"}])
    trace_dir = tmp_path / "trace"
    session.export_trace(trace_dir)

    session = reset_session()
    session.load_trace(trace_dir)
    session.enable_replay(ReplayPlan().live("agent.chat", 1))
    crossings: list[tuple] = []
    session.on_crossing = lambda *args: crossings.append(args)

    traced = wrap_llm("agent.chat", _complete)
    out = traced(
        "openai",
        "gpt-4o-mini",
        [{"role": "user", "content": "cutpoint"}],
    )

    assert out["completion"] == "openai/gpt-4o-mini:1"
    assert len(crossings) == 1
    bid, kind, inp, result = crossings[0]
    assert bid == "agent.chat"
    assert kind == "llm"
    assert inp.messages[0]["content"] == "cutpoint"
    assert session.captured_result("agent.chat", 1) == result


@pytest.mark.layer1
def test_wrap_llm_custom_extract_input():
    session = reset_session()
    session.enable_live()

    def extract_input(prompt: str) -> InputState:
        return InputState(
            messages=[{"role": "user", "content": prompt}],
            graph_state={"prompt": prompt},
        )

    def complete(prompt: str) -> dict:
        return {"completion": prompt.upper(), "finish_reason": "stop"}

    traced = wrap_llm("custom.chat", complete, extract_input=extract_input)
    out = traced("hi")

    assert out["completion"] == "HI"
    env = session._recorded_envelopes[0]
    assert env.boundary_kind == "llm"
    assert env.input_state.graph_state["prompt"] == "hi"
