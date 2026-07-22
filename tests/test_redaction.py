"""Redaction keeps envelope structure while masking secrets before storage."""

from __future__ import annotations

import pytest

from chronicle import boundary, default_redactors, redact_secrets, reset_session
from chronicle.envelope.store import EnvelopeStore

SECRET_KEY = "sk-ABCD1234efgh5678IJKL"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcDEF123456"


@pytest.mark.layer1
def test_redact_secrets_masks_known_shapes_and_keeps_text():
    r = redact_secrets()
    assert SECRET_KEY not in r(f"my key is {SECRET_KEY} ok")
    assert "[REDACTED]" in r(f"my key is {SECRET_KEY} ok")
    assert r("delete the production database record 4471") == (
        "delete the production database record 4471"
    )  # ordinary text is untouched


@pytest.mark.layer1
def test_llm_boundary_redacts_prompt_and_completion():
    @boundary("agent", kind="llm")
    def agent(state: dict) -> dict:
        return {"completion": f"sure, using {SECRET_KEY}", "finish_reason": "stop"}

    session = reset_session()
    session.redactors = default_redactors()
    session.begin_trace("t-redact")
    agent({"messages": [{"role": "user", "content": f"here is my token {SECRET_KEY}"}]})

    env = session._recorded_envelopes[-1]
    # Secret is gone from both input and output...
    assert SECRET_KEY not in env.model_dump_json()
    # ...but structure is intact: role preserved, finish_reason preserved.
    assert env.input_state.messages[0]["role"] == "user"
    assert env.action_result.finish_reason == "stop"


@pytest.mark.layer1
def test_tool_arguments_are_redacted():
    @boundary("call_api", kind="tool")
    def call_api(payload: dict) -> dict:
        return {"status": "ok", "tool_calls": [
            {"name": "call_api", "arguments": {"authorization": f"Bearer {JWT}"}}
        ]}

    session = reset_session()
    session.redactors = default_redactors()
    session.begin_trace("t-redact-tool")
    call_api({"authorization": f"Bearer {JWT}"})

    dumped = session._recorded_envelopes[-1].model_dump_json()
    assert JWT not in dumped
    assert "[REDACTED]" in dumped


@pytest.mark.layer1
def test_no_redactors_is_a_passthrough():
    @boundary("agent", kind="llm")
    def agent(state: dict) -> dict:
        return {"completion": f"token {SECRET_KEY}"}

    session = reset_session()  # no redactors set
    session.begin_trace("t-none")
    agent({"messages": []})

    assert SECRET_KEY in session._recorded_envelopes[-1].model_dump_json()


@pytest.mark.layer1
def test_stored_file_is_redacted(tmp_path):
    @boundary("agent", kind="llm")
    def agent(state: dict) -> dict:
        return {"completion": f"key {SECRET_KEY}", "finish_reason": "stop"}

    store_path = tmp_path / "runs.jsonl"
    session = reset_session()
    session.redactors = default_redactors()
    session.store = EnvelopeStore(store_path)
    session.begin_trace("t-file")
    agent({"messages": []})

    on_disk = store_path.read_text(encoding="utf-8")
    assert SECRET_KEY not in on_disk
    assert "[REDACTED]" in on_disk
