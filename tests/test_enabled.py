"""CHRONICLE_ENABLED kill switch for LIVE recording."""

from __future__ import annotations

import chronicle
from chronicle import ReplayPlan, boundary
from chronicle.envelope.capture import EnvelopeRecorder
from chronicle.envelope.store import EnvelopeStore
from chronicle.session import reset_session


def test_is_enabled_defaults_on(monkeypatch):
    monkeypatch.delenv("CHRONICLE_ENABLED", raising=False)
    assert chronicle.is_enabled() is True


def test_is_enabled_falsy_tokens(monkeypatch):
    for value in ("0", "false", "FALSE", "off", "no", " No "):
        monkeypatch.setenv("CHRONICLE_ENABLED", value)
        assert chronicle.is_enabled() is False, value


def test_is_enabled_truthy_tokens(monkeypatch):
    for value in ("1", "true", "yes", "on"):
        monkeypatch.setenv("CHRONICLE_ENABLED", value)
        assert chronicle.is_enabled() is True, value


def test_boundary_passthrough_when_disabled(monkeypatch):
    monkeypatch.setenv("CHRONICLE_ENABLED", "0")
    reset_session()

    @boundary("tool", kind="tool")
    def tool(x: str) -> dict:
        return {"value": x}

    with chronicle.record("t", store="unused.jsonl") as session:
        result = tool("hi")

    assert result == {"value": "hi"}
    assert session._recorded_envelopes == []
    assert session.store is None


def test_boundary_records_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONICLE_ENABLED", "1")
    reset_session()

    @boundary("tool", kind="tool")
    def tool(x: str) -> dict:
        return {"value": x}

    with chronicle.record("t", store=str(tmp_path / "runs.jsonl")) as session:
        tool("hi")

    assert len(session._recorded_envelopes) == 1


def test_replay_still_works_when_disabled(monkeypatch, tmp_path):
    """Fixtures and cut-point replay keep working even if CHRONICLE_ENABLED=0."""
    monkeypatch.setenv("CHRONICLE_ENABLED", "1")

    @boundary("tool", kind="tool")
    def tool(x: str) -> dict:
        return {"value": x}

    trace_dir = tmp_path / "trace"
    with chronicle.record("t", export=str(trace_dir)):
        tool("recorded")

    monkeypatch.setenv("CHRONICLE_ENABLED", "0")
    with chronicle.replay_trace(str(trace_dir), ReplayPlan().stub("tool", 1)):
        assert tool("ignored") == {"value": "recorded"}


def test_wrap_passthrough_when_disabled(monkeypatch):
    monkeypatch.setenv("CHRONICLE_ENABLED", "0")
    reset_session()

    class Completions:
        def create(self, **kwargs):
            return {"choices": [{"message": {"content": "ok"}}], "model": "m"}

    class Chat:
        completions = Completions()

    class Client:
        chat = Chat()

    client = chronicle.wrap(Client())
    with chronicle.record("t") as session:
        resp = client.chat.completions.create(model="m", messages=[])

    assert resp["choices"][0]["message"]["content"] == "ok"
    assert session._recorded_envelopes == []


def test_envelope_recorder_passthrough_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONICLE_ENABLED", "0")
    store = EnvelopeStore(tmp_path / "runs.jsonl")
    recorder = EnvelopeRecorder(store=store, model_version="m")

    @recorder.wrap_node("agent")
    def agent(state: dict) -> dict:
        return {**state, "completion": "done"}

    result = agent({"messages": []})
    assert result["completion"] == "done"
    assert store.read_all() == []
