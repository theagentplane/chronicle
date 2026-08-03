"""Replay checksum: canonicalization ignores volatile fields, a tampered fixture is
detected on load, and stubbed crossings are verified against the recorded order.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import chronicle
from chronicle import ChecksumMismatch, boundary
from chronicle.envelope.canonical import canonicalize, digest
from chronicle.envelope.schema import InputState
from chronicle.execution_graph import ExecutionGraph
from chronicle.replay.checksum import build_verifier, trace_checksum


# --- canonicalization -------------------------------------------------------------- #
def test_canonicalize_drops_volatile_and_sorts():
    a = {"amount": 100, "timestamp": "2026-01-01", "nested": {"run_id": "x", "keep": 1}}
    assert canonicalize(a) == {"amount": 100, "nested": {"keep": 1}}


def test_digest_is_stable_across_volatile_changes_but_not_real_changes():
    base = {"amount": 100, "timestamp": "t1"}
    same_but_volatile = {"amount": 100, "timestamp": "t2"}
    real_change = {"amount": 101, "timestamp": "t1"}
    assert digest(base) == digest(same_but_volatile)  # timestamp ignored
    assert digest(base) != digest(real_change)  # amount matters


# --- fixture integrity on load ----------------------------------------------------- #
def _record(tmp_path: Path, ts: str = "2026-01-01T00:00:00Z") -> str:
    @boundary("agent", kind="llm")
    def agent(state):
        return {**state, "completion": "x", "finish_reason": "stop"}

    @boundary(
        "tool",
        kind="tool",
        extract_input=lambda *a, **k: InputState(
            messages=[], graph_state={"amount": 100, "timestamp": ts}
        ),
    )
    def tool(amount):
        return {"ok": amount}

    fixture = str(tmp_path / "trace")
    with chronicle.record("t", export=fixture):
        state = agent({"messages": []})
        tool(100)
        agent(state)
    return fixture


def _tool_fixture_file(fixture: str) -> Path:
    meta = json.loads((Path(fixture) / "graph.json").read_text())
    entry = next(n for n in meta["nodes"] if n["boundary_id"] == "tool")
    return Path(fixture) / entry["fixture"]


def _edit_tool_input(fixture: str, key: str, value) -> None:
    path = _tool_fixture_file(fixture)
    data = json.loads(path.read_text())
    data["input_state"]["graph_state"][key] = value
    path.write_text(json.dumps(data))


def test_volatile_field_edit_does_not_false_fire(tmp_path):
    fixture = _record(tmp_path)
    _edit_tool_input(fixture, "timestamp", "totally-different-time")
    # Reloading must not raise: the volatile field is normalized before hashing.
    ExecutionGraph.load(fixture)


def test_nonvolatile_edit_is_detected(tmp_path):
    fixture = _record(tmp_path)
    _edit_tool_input(fixture, "amount", 999)
    with pytest.raises(ChecksumMismatch):
        ExecutionGraph.load(fixture)


# --- replay-order verifier --------------------------------------------------------- #
def test_verifier_accepts_recorded_order(tmp_path):
    fixture = _record(tmp_path)
    graph = ExecutionGraph.load(fixture)
    verifier = build_verifier(graph.timeline(), lambda _b, _i: True)  # stub all
    for env in graph.timeline():
        verifier.check(env.node_id, env.invocation_index, env)  # in order: no raise


def test_verifier_flags_out_of_order(tmp_path):
    fixture = _record(tmp_path)
    graph = ExecutionGraph.load(fixture)
    order = graph.timeline()  # agent@1, tool@1, agent@2
    verifier = build_verifier(order, lambda _b, _i: True)
    # Serve the second crossing first: a reorder / removal of the first.
    with pytest.raises(ChecksumMismatch):
        verifier.check(order[1].node_id, order[1].invocation_index, order[1])


def test_verifier_flags_extra_stub(tmp_path):
    fixture = _record(tmp_path)
    graph = ExecutionGraph.load(fixture)
    order = graph.timeline()
    verifier = build_verifier(order, lambda _b, _i: True)
    for env in order:
        verifier.check(env.node_id, env.invocation_index, env)
    with pytest.raises(ChecksumMismatch):  # one crossing beyond the recorded subsequence
        verifier.check(order[0].node_id, 99, order[0])


def test_full_replay_of_a_clean_trace_passes(tmp_path):
    fixture = _record(tmp_path)
    with chronicle.replay_trace(fixture, chronicle.ReplayPlan()):
        # Re-run the same shape; every stubbed crossing matches the recorded order.
        @boundary("agent", kind="llm")
        def agent(state):
            return {**state}

        @boundary("tool", kind="tool")
        def tool(amount):
            return {"ok": amount}

        state = agent({"messages": []})
        tool(100)
        agent(state)  # no ChecksumMismatch


def test_checksum_present_in_graph_json(tmp_path):
    fixture = _record(tmp_path)
    meta = json.loads((Path(fixture) / "graph.json").read_text())
    assert isinstance(meta.get("checksum"), str) and len(meta["checksum"]) == 64
    # Recomputing from the committed envelopes reproduces it.
    graph = ExecutionGraph.load(fixture)
    assert trace_checksum(graph.timeline()) == meta["checksum"]
