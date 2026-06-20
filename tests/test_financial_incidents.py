"""Cut-point tests for financial incident demos."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chronicle.replay.plan import ReplayPlan
from chronicle.session import reset_session

from examples.financial_incidents import invoice_currency, refund_order_id, trade_notional

FIXTURES = ROOT / "fixtures" / "traces"


@pytest.mark.parametrize(
    "scenario, outcome_key",
    [
        (refund_order_id, "refunded"),
        (invoice_currency, "invoice_sent"),
        (trade_notional, "filled"),
    ],
)
@pytest.mark.layer1
def test_cutpoint_replay_blocks_incident(scenario, outcome_key):
    # Set up the path to the trace directory for the scenario
    trace_dir = FIXTURES / scenario.NAME

    # Skip the test if the trace directory doesn't exist (user must record it first)
    if not trace_dir.exists():
        pytest.skip(f"Run: python examples/financial_incidents/run.py {scenario.NAME.split('-')[0]} record")

    scenario.set_mode("gated")

    # Reset the chronicle session, load the corresponding trace, and prepare for replay with the correct stubbing plan
    session = reset_session()
    session.load_trace(trace_dir)
    session.enable_replay(
    # Stub the first agent LLM, run the tool and the second agent live
        ReplayPlan().stub("agent", 1).live(scenario.TOOL, 1).live("agent", 2)
    )

    # Run the scenario agent, passing a stubbed user message just for cut-point triggering
    result = scenario.run_agent(user_message="stubbed")

    # Capture the result from the tool boundary at invocation index 1
    live = session.captured_result(scenario.TOOL, 1)

    # Assert that the incident resulted in the action being blocked
    assert live.get("blocked") is True