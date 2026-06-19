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
    trace_dir = FIXTURES / scenario.NAME
    if not trace_dir.exists():
        pytest.skip(f"Run: python examples/financial_incidents/run.py {scenario.NAME.split('-')[0]} record")

    scenario.set_mode("gated")

    session = reset_session()
    session.load_trace(trace_dir)
    session.enable_replay(
        ReplayPlan().stub("agent", 1).live(scenario.TOOL, 1).live("agent", 2)
    )

    result = scenario.run_agent(user_message="stubbed")
    live = session.captured_result(scenario.TOOL, 1)

    assert live.get("blocked") is True
    assert result.get(outcome_key) is False
    assert result.get("blocked") is True
    assert session.call_log()[0].mode == "stub"
    assert any(c.mode == "live" and c.boundary_id == scenario.TOOL for c in session.call_log())