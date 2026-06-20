#!/usr/bin/env python3
"""Record a production deletion incident (ungated tool, no env protection)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from examples.deletion_agent.agent_bench import run_deletion_agent, set_delete_impl
from chronicle.envelope.store import EnvelopeStore
from chronicle.session import get_session, reset_session

TRACE_DIR = ROOT / "fixtures" / "traces" / "deletion-incident-001"
STORE_PATH = ROOT / ".chronicle" / "runs" / "deletion-incident.jsonl"


def main() -> None:
    set_delete_impl("ungated")

    session = reset_session()
    session.build_id = os.environ.get("CHRONICLE_BUILD_ID", "deletion-demo-record")
    session.store = EnvelopeStore(STORE_PATH)
    session.begin_trace("trace-deletion-incident-001")

    result = run_deletion_agent(
        user_message="Clean up old application logs in production",
        environment="prod",
    )

    print("=== INCIDENT RECORDED ===")
    print(f"Trace ID: {session.trace_id}")
    print(f"Deleted prod data: {result.get('deleted')}")
    print(f"Blocked: {result.get('blocked')}")
    print(f"Completion: {result.get('completion')}")
    print()

    export_path = session.export_trace(TRACE_DIR)
    print(f"Exported trace to: {export_path}")
    print(f"Envelopes recorded: {len(session._recorded_envelopes)}")
    print()
    print("Run: python examples/deletion_agent/show_trace.py")


if __name__ == "__main__":
    main()
