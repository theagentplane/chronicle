#!/usr/bin/env python3
"""Run cut-point replay demo: stub agent, live gated delete_file."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from examples.deletion_agent.agent_bench import run_deletion_agent, set_delete_impl
from chronicle.replay.plan import ReplayPlan
from chronicle.session import reset_session

TRACE_DIR = ROOT / "fixtures" / "traces" / "deletion-incident-001"


def main() -> None:
    if not TRACE_DIR.exists():
        print("No recorded trace found. Run record_incident.py first.")
        sys.exit(1)

    set_delete_impl("gated")

    session = reset_session()
    graph = session.load_trace(TRACE_DIR)
    plan = ReplayPlan().stub("agent", 1).live("delete_file", 1).live("agent", 2)
    session.enable_replay(plan)

    print("=== CUT-POINT REPLAY ===")
    print("Plan: stub agent@1, LIVE delete_file@1 (gated), LIVE agent@2")
    print()

    result = run_deletion_agent(user_message="stubbed", environment="prod")

    live_result = session.captured_result("delete_file", 1)
    print(f"delete_file input:  path=/prod/logs/app.log env=prod")
    print(f"delete_file output: {live_result}")
    print(f"final completion:   {result['completion']}")
    print()

    checks = [
        ("delete_file blocked prod", live_result.get("blocked") is True),
        ("prod data not deleted", result.get("deleted") is False),
        ("agent@1 was stubbed", session.call_log()[0].mode == "stub"),
        ("delete_file ran live", any(c.mode == "live" and c.boundary_id == "delete_file" for c in session.call_log())),
    ]

    all_pass = True
    for name, passed in checks:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
        all_pass = all_pass and passed

    if not all_pass:
        sys.exit(1)
    print()
    print("Cut-point replay passed.")


if __name__ == "__main__":
    main()
