"""One-call record() / replay_trace() context managers.

These wrap the existing session API, so the tests focus on the ergonomics:
setup happens for you, and a record then replay round trip behaves the same as
the longhand form.
"""

from __future__ import annotations

import pytest

import chronicle
from chronicle import ReplayPlan, boundary

SECRET = "sk-ABCD1234efgh5678IJKL"


@pytest.mark.layer1
def test_record_then_replay_trace_roundtrip(tmp_path):
    @boundary("tool", kind="tool")
    def tool(x: str) -> dict:
        return {"status": "done", "value": x}

    trace_dir = tmp_path / "trace"
    with chronicle.record(
        "t1", store=str(tmp_path / "runs.jsonl"), export=str(trace_dir)
    ) as session:
        tool("real")

    # Recording happened, the store was written, and the trace was exported.
    assert len(session._recorded_envelopes) == 1
    assert (tmp_path / "runs.jsonl").read_text(encoding="utf-8").strip()
    assert trace_dir.exists()

    # Replaying the exported trace stubs the tool with its recorded result.
    with chronicle.replay_trace(str(trace_dir), ReplayPlan().stub("tool", 1)):
        result = tool("ignored-in-replay")

    assert result["status"] == "done"
    assert result["value"] == "real"


@pytest.mark.layer1
def test_record_applies_redactors(tmp_path):
    @boundary("agent", kind="llm")
    def agent(state: dict) -> dict:
        return {"completion": f"key {SECRET}", "finish_reason": "stop"}

    with chronicle.record("t", redactors=chronicle.default_redactors()) as session:
        agent({"messages": []})

    assert SECRET not in session._recorded_envelopes[-1].model_dump_json()


@pytest.mark.layer1
def test_record_without_export_leaves_no_fixture(tmp_path):
    @boundary("agent", kind="llm")
    def agent(state: dict) -> dict:
        return {"completion": "ok"}

    with chronicle.record("t") as session:
        agent({"messages": []})

    assert len(session._recorded_envelopes) == 1  # recorded in memory, nothing exported
