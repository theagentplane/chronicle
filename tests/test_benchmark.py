"""Tests for the incident benchmark: every scenario detects its fault, tolerates a
benign change, and replays deterministically with zero model calls.

These assert the correctness metrics the paper reports (detection, specificity,
determinism, zero replay model calls). Timing is exercised by running the harness; it
is not asserted here to keep the suite fast.
"""

from __future__ import annotations

import pytest

from examples.benchmark import harness

SCENARIOS = list(harness.SCENARIOS.items())


@pytest.mark.parametrize("name,mod", SCENARIOS, ids=[n for n, _ in SCENARIOS])
def test_scenario_exposes_interface(name, mod):
    for attr in ("NAME", "TRACE_ID", "TOOL"):
        assert isinstance(getattr(mod, attr), str)
    for fn in ("set_mode", "safe", "run_agent"):
        assert callable(getattr(mod, fn))
    with pytest.raises(ValueError):
        mod.set_mode("nonsense")


@pytest.mark.parametrize("name,mod", SCENARIOS, ids=[n for n, _ in SCENARIOS])
def test_records_three_crossings(name, mod, tmp_path):
    trace_dir, crossings, store_bytes = harness._record_incident(mod, tmp_path)
    assert crossings == 3  # agent -> tool -> agent
    assert store_bytes > 0
    assert trace_dir.exists()
    assert list(trace_dir.glob("*.json"))  # exported fixture files


@pytest.mark.parametrize("name,mod", SCENARIOS, ids=[n for n, _ in SCENARIOS])
def test_detection_and_specificity(name, mod, tmp_path):
    trace_dir, _, _ = harness._record_incident(mod, tmp_path)
    # Detection: the unguarded incident must trip the cut-point test (not safe).
    assert harness._cutpoint_safe(mod, trace_dir, "ungated") is False
    # Specificity: the guarded fix and a benign unrelated change must pass.
    assert harness._cutpoint_safe(mod, trace_dir, "gated") is True
    assert harness._cutpoint_safe(mod, trace_dir, "benign") is True


@pytest.mark.parametrize("name,mod", SCENARIOS, ids=[n for n, _ in SCENARIOS])
def test_replay_is_deterministic_with_zero_model_calls(name, mod, tmp_path):
    trace_dir, _, _ = harness._record_incident(mod, tmp_path)
    deterministic, live_crossings = harness._replay_determinism(mod, trace_dir)
    assert deterministic
    assert live_crossings == 0  # full-stub replay makes no live (model) calls


def test_benign_differs_from_gated_but_stays_safe(tmp_path):
    """The benign variant is a genuine unrelated change (different output), yet the
    safety invariant still holds, so it is not just a copy of the gated fix."""
    mod = harness.refund_order_id
    mod.set_mode("gated")
    gated = mod.issue_refund.__wrapped__(mod.ORDER_ID, mod.BAD_AMOUNT_CENTS)
    mod.set_mode("benign")
    benign = mod.issue_refund.__wrapped__(mod.ORDER_ID, mod.BAD_AMOUNT_CENTS)
    mod.set_mode("ungated")
    assert gated["blocked"] is True and benign["blocked"] is True  # both safe
    assert benign != gated  # but the benign change is real (audit_id / message)
    assert "audit_id" in benign


@pytest.mark.parametrize("name,mod", SCENARIOS, ids=[n for n, _ in SCENARIOS])
def test_over_fitting_resistance(name, mod, tmp_path):
    trace_dir, _, _ = harness._record_incident(mod, tmp_path)
    survived, total = harness._benign_specificity(mod, trace_dir)
    assert total >= 5
    assert survived == total  # invariant to every unrelated output change


def test_benign_sweep_is_not_vacuous(tmp_path):
    """Negative control: a transform that unblocks the tool must NOT survive, proving
    the sweep would catch a genuine safety regression."""
    import chronicle
    from chronicle import ReplayPlan

    mod = harness.refund_order_id
    trace_dir, _, _ = harness._record_incident(mod, tmp_path)
    mod.set_mode("gated")
    session = chronicle.reset_session()
    session.load_trace(trace_dir)
    session.enable_replay(ReplayPlan().stub("agent", 1).live(mod.TOOL, 1).live("agent", 2))
    result = mod.run_agent(user_message="stubbed")
    live = session.captured_result(mod.TOOL, 1)

    broken = {**live, "blocked": False, "status": "refunded"}  # safety-breaking change
    downstream = mod.agent_finalize.__wrapped__(dict(result), broken)
    assert mod.safe(downstream, broken) is False
