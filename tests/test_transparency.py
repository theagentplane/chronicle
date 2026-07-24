"""The @boundary wrapper is transparent: it never changes what the function
returns or raises, and zero-config capture records the real call by name."""

from __future__ import annotations

import pytest

from chronicle import boundary, reset_session


@pytest.mark.layer1
def test_extract_result_does_not_change_the_return():
    @boundary("agent", kind="llm", extract_result=lambda r: {"completion": "RECORDED-ONLY"})
    def agent(state: dict) -> dict:
        return {"completion": "real", "finish_reason": "stop"}

    session = reset_session()
    session.begin_trace("t")
    out = agent({"messages": []})

    # Caller gets the real value; the extractor only shaped the envelope.
    assert out == {"completion": "real", "finish_reason": "stop"}
    assert session._recorded_envelopes[-1].action_result.completion == "RECORDED-ONLY"


@pytest.mark.layer1
def test_on_crossing_sees_the_original_result():
    seen: list = []

    @boundary("t", kind="tool", extract_result=lambda r: {"status": "recorded"})
    def tool(x: int) -> dict:
        return {"status": "real", "x": x}

    session = reset_session()
    session.on_crossing = lambda bid, kind, inp, result: seen.append(result)
    session.begin_trace("t")
    tool(5)

    assert seen[-1] == {"status": "real", "x": 5}


@pytest.mark.layer1
def test_failure_records_an_error_envelope_and_reraises():
    @boundary("boom", kind="tool")
    def boom(x: int) -> dict:
        raise RuntimeError("kaboom")

    session = reset_session()
    session.begin_trace("t")
    with pytest.raises(RuntimeError, match="kaboom"):
        boom(1)

    env = session._recorded_envelopes[-1]
    assert env.action_result.error == "kaboom"
    assert env.action_result.error_type == "RuntimeError"
    assert env.action_result.finish_reason == "error"


@pytest.mark.layer1
def test_zero_config_records_args_by_name():
    @boundary("complete", kind="llm")
    def complete(provider, model, messages, temperature=0.0):
        return {"completion": "ok", "finish_reason": "stop"}

    session = reset_session()
    session.begin_trace("t")
    complete("openai", "gpt-4o", [{"role": "user", "content": "hi"}], temperature=0.3)

    gs = session._recorded_envelopes[-1].input_state.graph_state
    assert gs["provider"] == "openai"
    assert gs["model"] == "gpt-4o"
    assert gs["temperature"] == 0.3
    assert session._recorded_envelopes[-1].input_state.messages == [{"role": "user", "content": "hi"}]


@pytest.mark.layer1
def test_opaque_argument_does_not_break_recording():
    class Client:  # not JSON-serializable
        def __repr__(self) -> str:
            return "<Client>"

    @boundary("call", kind="tool")
    def call(client, path):
        return {"status": "ok"}

    session = reset_session()
    session.begin_trace("t")
    out = call(Client(), "/x")

    assert out == {"status": "ok"}  # capture never breaks the call
    gs = session._recorded_envelopes[-1].input_state.graph_state
    assert gs["client"] == "<Client>"  # opaque object -> repr
    assert gs["path"] == "/x"
