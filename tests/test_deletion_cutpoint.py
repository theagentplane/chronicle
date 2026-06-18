"""Cut-point replay test: stub agent, run gated delete_file live."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from examples.deletion_agent.agent_bench import delete_file, run_deletion_agent, set_delete_impl
from chronicle.replay.plan import ReplayPlan
from chronicle.session import get_session, reset_session

TRACE_DIR = ROOT / "fixtures" / "traces" / "deletion-incident-001"


@pytest.fixture
def incident_graph():
    if not TRACE_DIR.exists():
        pytest.skip("Run record_incident.py first to generate fixtures")
    return TRACE_DIR


@pytest.mark.layer1
def test_cutpoint_delete_file_blocks_prod(incident_graph):
    """
    Incident: ungated delete_file removed prod data.

    Fix: gated delete_file blocks prod. Agent behavior unchanged (stubbed).
    Cut-point: run delete_file live with the fix; assert prod is protected.
    """
    set_delete_impl("gated")

    session = reset_session()
    graph = session.load_trace(incident_graph)
    plan = ReplayPlan().stub("agent", 1).live("delete_file", 1).live("agent", 2)
    session.enable_replay(plan)

    # Run orchestrator — agent stubbed from fixture, delete_file runs live (gated)
    result = run_deletion_agent(
        user_message="ignored in replay — agent is stubbed",
        environment="prod",
    )

    # --- upstream fidelity: agent_plan stubbed from incident fixture ---
    agent_calls = [c for c in session.call_log() if c.boundary_id == "agent"]
    assert len(agent_calls) == 2
    assert agent_calls[0].mode == "stub"
    assert agent_calls[1].mode == "live"

    # --- cut-point input: delete_file received same args as incident ---
    prod_delete = graph.envelope("delete_file", invocation_index=1)
    live_input = session.captured_input("delete_file", 1)
    assert live_input is not None
    assert live_input.graph_state["path"] == "/prod/logs/app.log"
    assert live_input.graph_state["environment"] == "prod"
    assert live_input.graph_state == prod_delete.input_state.graph_state

    # --- cut-point output: gated tool blocks prod (the fix) ---
    live_result = session.captured_result("delete_file", 1)
    assert live_result["blocked"] is True
    assert live_result["status"] == "blocked"
    assert "production" in live_result["message"].lower()

    # --- downstream: finalize used blocked result ---
    assert result["blocked"] is True
    assert result["deleted"] is False
    assert "blocked" in result["completion"].lower()


@pytest.mark.layer1
def test_gated_delete_file_directly():
    """Sanity check: gated implementation blocks prod."""
    set_delete_impl("gated")
    session = reset_session()
    session.enable_live()

    result = delete_file("/prod/logs/app.log", "prod")
    assert result["blocked"] is True
    assert result["status"] == "blocked"
