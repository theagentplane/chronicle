"""Unit tests for ChronicleSession.on_crossing hook."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chronicle.boundary import boundary
from chronicle.envelope.schema import InputState
from chronicle.replay.plan import ReplayPlan
from chronicle.session import reset_session


@boundary("echo_tool", kind="tool")
def echo_tool(value: str) -> dict:
    return {"status": "ok", "value": value}


@pytest.mark.layer1
def test_on_crossing_invoked_in_live_record():
    session = reset_session()
    session.enable_live()
    crossings: list[tuple] = []

    def hook(boundary_id, kind, input_state, result):
        crossings.append((boundary_id, kind, input_state, result))

    session.on_crossing = hook

    out = echo_tool("hello")
    assert out == {"status": "ok", "value": "hello"}
    assert len(crossings) == 1
    bid, kind, inp, result = crossings[0]
    assert bid == "echo_tool"
    assert kind == "tool"
    assert isinstance(inp, InputState)
    assert result == {"status": "ok", "value": "hello"}


@pytest.mark.layer1
def test_on_crossing_invoked_at_live_cutpoint(tmp_path):
    # Record a fixture envelope first
    session = reset_session()
    session.enable_live()
    echo_tool("fixture")
    trace_dir = tmp_path / "trace"
    session.export_trace(trace_dir)

    # Replay with LIVE cut-point and hook
    session = reset_session()
    session.load_trace(trace_dir)
    session.enable_replay(ReplayPlan().live("echo_tool", 1))
    crossings: list[tuple] = []
    session.on_crossing = lambda *args: crossings.append(args)

    out = echo_tool("cutpoint")
    assert out == {"status": "ok", "value": "cutpoint"}
    assert len(crossings) == 1
    bid, kind, inp, result = crossings[0]
    assert bid == "echo_tool"
    assert kind == "tool"
    assert result["value"] == "cutpoint"
    assert session.captured_result("echo_tool", 1) == result


@pytest.mark.layer1
def test_on_crossing_not_invoked_when_stubbed(tmp_path):
    session = reset_session()
    session.enable_live()
    echo_tool("fixture")
    trace_dir = tmp_path / "trace"
    session.export_trace(trace_dir)

    session = reset_session()
    session.load_trace(trace_dir)
    session.enable_replay(ReplayPlan().stub("echo_tool", 1))
    crossings: list[tuple] = []
    session.on_crossing = lambda *args: crossings.append(args)

    out = echo_tool("ignored")
    assert out["value"] == "fixture"  # stubbed from fixture
    assert crossings == []


@pytest.mark.layer1
def test_on_crossing_none_is_noop():
    session = reset_session()
    session.enable_live()
    assert session.on_crossing is None
    assert echo_tool("x")["value"] == "x"
