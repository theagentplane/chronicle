"""E2E: ``on_crossing`` as the cost-management integration point.

Chronicle stays agnostic of TokenOps (and any ledger). External cost observers
plug in via ``ChronicleSession.on_crossing`` — the same hook TokenOps uses.
These tests prove that contract with a tiny in-file fake ledger/governor.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chronicle.boundary import boundary
from chronicle.envelope.schema import InputState
from chronicle.replay.plan import ReplayPlan
from chronicle.session import reset_session


# ---------------------------------------------------------------------------
# Fake cost manager (test double only — not part of the chronicle package)
# ---------------------------------------------------------------------------


class BudgetExceeded(Exception):
    """Raised by the fake governor when cumulative spend exceeds budget."""

    def __init__(self, spend: float, budget: float, boundary_id: str):
        self.spend = spend
        self.budget = budget
        self.boundary_id = boundary_id
        super().__init__(
            f"budget exceeded at {boundary_id!r}: spend={spend} > budget={budget}"
        )


@dataclass
class CrossingSpend:
    boundary_id: str
    kind: str
    cost: float
    result: Any


@dataclass
class FakeCostManager:
    """Minimal ledger + governor that observes ``@boundary`` crossings.

    Models the TokenOps plug-in pattern: install ``on_crossing``, accumulate
    spend, and signal halt/reject when a fake budget is exceeded.
    """

    budget: float
    cost_by_boundary: dict[str, float] = field(default_factory=dict)
    default_cost: float = 1.0
    spend: float = 0.0
    halted: bool = False
    crossings: list[CrossingSpend] = field(default_factory=list)

    def cost_for(self, boundary_id: str) -> float:
        return self.cost_by_boundary.get(boundary_id, self.default_cost)

    def on_crossing(
        self,
        boundary_id: str,
        kind: str,
        input_state: InputState,
        result: Any,
    ) -> None:
        if self.halted:
            raise BudgetExceeded(self.spend, self.budget, boundary_id)

        cost = self.cost_for(boundary_id)
        self.spend += cost
        self.crossings.append(
            CrossingSpend(boundary_id=boundary_id, kind=kind, cost=cost, result=result)
        )
        if self.spend > self.budget:
            self.halted = True
            raise BudgetExceeded(self.spend, self.budget, boundary_id)


@boundary("search", kind="tool")
def search(query: str) -> dict:
    return {"status": "ok", "hits": [query], "tokens": 10}


@boundary("summarize", kind="tool")
def summarize(text: str) -> dict:
    return {"status": "ok", "summary": text[:20], "tokens": 25}


@boundary("expensive_call", kind="tool")
def expensive_call(label: str) -> dict:
    return {"status": "ok", "label": label, "tokens": 100}


# ---------------------------------------------------------------------------
# E2E scenarios
# ---------------------------------------------------------------------------


@pytest.mark.layer1
def test_e2e_observer_records_spend_and_envelopes():
    """LIVE record: envelopes written AND cost observer runs for each crossing."""
    session = reset_session()
    session.enable_live()
    session.begin_trace("cost-e2e-record")

    manager = FakeCostManager(
        budget=100.0,
        cost_by_boundary={"search": 10.0, "summarize": 25.0},
    )
    session.on_crossing = manager.on_crossing

    assert search("pricing")["hits"] == ["pricing"]
    assert summarize("long agent output")["status"] == "ok"

    assert len(session._recorded_envelopes) == 2
    assert [e.node_id for e in session._recorded_envelopes] == ["search", "summarize"]
    assert len(manager.crossings) == 2
    assert manager.spend == 35.0
    assert manager.halted is False
    assert manager.crossings[0].boundary_id == "search"
    assert manager.crossings[0].cost == 10.0
    assert manager.crossings[1].boundary_id == "summarize"
    assert manager.crossings[1].cost == 25.0


@pytest.mark.layer1
def test_e2e_budget_exceeded_signals_halt():
    """When spend exceeds budget, the handler raises and sets halted."""
    session = reset_session()
    session.enable_live()
    session.begin_trace("cost-e2e-halt")

    manager = FakeCostManager(budget=15.0, cost_by_boundary={"search": 10.0})
    session.on_crossing = manager.on_crossing

    search("first")  # spend=10, under budget
    with pytest.raises(BudgetExceeded) as exc_info:
        search("second")  # spend=20 > 15

    err = exc_info.value
    assert err.boundary_id == "search"
    assert err.spend == 20.0
    assert err.budget == 15.0
    assert manager.halted is True
    # Envelope for the crossing that tipped the budget is still recorded
    # (on_crossing runs after LIVE record — observer reacts, does not undo).
    assert len(session._recorded_envelopes) == 2
    assert len(manager.crossings) == 2


@pytest.mark.layer1
def test_e2e_halted_rejects_subsequent_crossings():
    """Once halted, further crossings are rejected without adding spend."""
    session = reset_session()
    session.enable_live()
    session.begin_trace("cost-e2e-reject")

    manager = FakeCostManager(
        budget=5.0,
        cost_by_boundary={"expensive_call": 10.0, "search": 1.0},
    )
    session.on_crossing = manager.on_crossing

    with pytest.raises(BudgetExceeded):
        expensive_call("blow-budget")

    assert manager.halted is True
    spend_after_halt = manager.spend

    with pytest.raises(BudgetExceeded):
        search("should-reject")

    assert manager.spend == spend_after_halt
    # search still executed + recorded before on_crossing rejected
    assert len(session._recorded_envelopes) == 2
    assert session._recorded_envelopes[-1].node_id == "search"


@pytest.mark.layer1
def test_e2e_stub_replay_does_not_call_on_crossing(tmp_path):
    """STUB replay returns fixtures without invoking the cost observer."""
    session = reset_session()
    session.enable_live()
    session.begin_trace("cost-e2e-fixture")
    search("fixture-query")
    summarize("fixture-text")
    trace_dir = tmp_path / "trace"
    session.export_trace(trace_dir)

    session = reset_session()
    session.load_trace(trace_dir)
    session.enable_replay(ReplayPlan().stub("search", 1).stub("summarize", 1))

    manager = FakeCostManager(budget=100.0, default_cost=50.0)
    session.on_crossing = manager.on_crossing

    out = search("ignored")
    out2 = summarize("ignored")

    assert out["hits"] == ["fixture-query"]
    assert out2["summary"] == "fixture-text"[:20]
    assert manager.crossings == []
    assert manager.spend == 0.0
    assert manager.halted is False


@pytest.mark.layer1
def test_e2e_live_cutpoint_still_observes_cost(tmp_path):
    """LIVE cut-point executes the tool and still bills the observer."""
    session = reset_session()
    session.enable_live()
    search("fixture")
    trace_dir = tmp_path / "trace"
    session.export_trace(trace_dir)

    session = reset_session()
    session.load_trace(trace_dir)
    session.enable_replay(ReplayPlan().live("search", 1))

    manager = FakeCostManager(budget=100.0, cost_by_boundary={"search": 7.5})
    session.on_crossing = manager.on_crossing

    out = search("cutpoint-query")
    assert out["hits"] == ["cutpoint-query"]
    assert len(manager.crossings) == 1
    assert manager.spend == 7.5
    assert session.captured_result("search", 1) == out


@pytest.mark.layer1
def test_e2e_multi_crossing_cumulative_spend():
    """Several distinct boundaries accumulate spend until the budget trips."""
    session = reset_session()
    session.enable_live()
    session.begin_trace("cost-e2e-cumulative")

    manager = FakeCostManager(
        budget=40.0,
        cost_by_boundary={
            "search": 10.0,
            "summarize": 25.0,
            "expensive_call": 100.0,
        },
    )
    session.on_crossing = manager.on_crossing

    search("a")  # 10
    search("b")  # 20
    with pytest.raises(BudgetExceeded) as exc_info:
        summarize("c")  # 45 > 40

    assert exc_info.value.spend == 45.0
    assert manager.spend == 45.0
    assert [c.boundary_id for c in manager.crossings] == [
        "search",
        "search",
        "summarize",
    ]
    assert len(session._recorded_envelopes) == 3

    # Subsequent expensive call is rejected while halted
    with pytest.raises(BudgetExceeded):
        expensive_call("nope")
    assert manager.spend == 45.0
    assert len(manager.crossings) == 3
