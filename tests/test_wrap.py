"""chronicle.wrap(client) records with no decorators and replays without calling
the API; chronicle.instrument_langgraph wraps nodes in one call. The fake client
mirrors the OpenAI chat response shape (resp.choices[0].message.content)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

import chronicle
from chronicle import ReplayPlan, reset_session


# --- a fake OpenAI-style client (pydantic, like the real SDK responses) ----- #
class _Message(BaseModel):
    content: str


class _Choice(BaseModel):
    message: _Message


class _Usage(BaseModel):
    prompt_tokens: int = 3
    completion_tokens: int = 2


class _Resp(BaseModel):
    model: str
    choices: list[_Choice]
    usage: _Usage


class _Completions:
    def __init__(self, calls: list) -> None:
        self.calls = calls

    def create(self, *, model, messages, **kwargs):
        self.calls.append((model, messages, kwargs))
        return _Resp(model=model, choices=[_Choice(message=_Message(content=f"hi from {model}"))], usage=_Usage())


class FakeOpenAI:
    def __init__(self) -> None:
        self.calls: list = []
        self.chat = type("Chat", (), {"completions": _Completions(self.calls)})()


@pytest.mark.layer1
def test_wrap_records_and_is_transparent():
    client = chronicle.wrap(FakeOpenAI())
    session = reset_session()
    session.begin_trace("t")

    resp = client.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": "hi"}], temperature=0.2
    )

    # Transparent: the caller gets the real response object.
    assert resp.choices[0].message.content == "hi from gpt-4o"
    env = session._recorded_envelopes[-1]
    assert env.boundary_kind == "llm"
    assert env.action_result.completion == "hi from gpt-4o"
    assert env.metadata.model_version == "gpt-4o"
    assert env.metadata.sampling_params.temperature == 0.2
    assert env.action_result.token_usage == {"prompt_tokens": 3, "completion_tokens": 2}


@pytest.mark.layer1
def test_wrap_replay_returns_recorded_and_makes_no_call(tmp_path):
    fake = FakeOpenAI()
    client = chronicle.wrap(fake)

    session = reset_session()
    session.begin_trace("t")
    client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])
    trace = tmp_path / "trace"
    session.export_trace(str(trace))
    calls_after_record = len(fake.calls)

    replay = reset_session()
    replay.load_trace(str(trace))
    replay.enable_replay(ReplayPlan().stub("llm", 1))
    resp = client.chat.completions.create(model="IGNORED", messages=[{"role": "user", "content": "IGNORED"}])

    # Recorded response reconstructed with attribute/index access, no new API call.
    assert resp.choices[0].message.content == "hi from gpt-4o"
    assert len(fake.calls) == calls_after_record


@pytest.mark.layer1
def test_instrument_langgraph_wraps_every_node():
    def agent(state: dict) -> dict:
        return {**state, "completion": "ok"}

    def tools(state: dict) -> dict:
        return {**state, "ran": True}

    nodes = chronicle.instrument_langgraph({"agent": agent, "tools": tools})

    session = reset_session()
    session.begin_trace("t")
    out = nodes["agent"]({"messages": [{"role": "user", "content": "hi"}]})
    assert out["completion"] == "ok"  # transparent
    assert nodes["tools"]({"messages": []})["ran"] is True

    assert len(session._recorded_envelopes) == 2
    assert {e.node_id for e in session._recorded_envelopes} == {"agent", "tools"}


@pytest.mark.layer1
def test_wrap_rejects_unknown_client():
    with pytest.raises(TypeError):
        chronicle.wrap(object())
