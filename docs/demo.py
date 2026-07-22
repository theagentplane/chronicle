"""Self-contained Chronicle demo. Renders docs/demo.gif via docs/demo.tape.

Records an incident where an agent deletes production data, then a cut-point
test verifies the gated fix, deterministically, with no LLM calls.

    python docs/demo.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import chronicle
from chronicle import ReplayPlan, boundary

GREEN, RED, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


@boundary("agent", kind="llm")
def agent(state: dict) -> dict:
    # The model decides to delete a record.
    return {
        "completion": "deleting order 4471",
        "finish_reason": "tool_calls",
        "tool_calls": [
            {
                "name": "delete_file",
                "arguments": {"path": "orders/4471", "environment": "production"},
            }
        ],
    }


@boundary("delete_file", kind="tool")
def delete_file_ungated(path: str, environment: str) -> dict:
    # The bug: no guard. It wipes prod.
    return {"status": "deleted", "path": path}


@boundary("delete_file", kind="tool")
def delete_file_gated(path: str, environment: str) -> dict:
    # The fix: refuse destructive ops in production.
    if environment == "production":
        return {"blocked": True, "reason": "guard: destructive op refused in prod"}
    return {"status": "deleted", "path": path}


def run(delete_fn) -> None:
    decision = agent({"messages": [{"role": "user", "content": "clean up order 4471"}]})
    args = decision["tool_calls"][0]["arguments"]
    delete_fn(args["path"], args["environment"])


def main() -> None:
    trace = Path(tempfile.mkdtemp()) / "incident"

    print(f"{BOLD}1. Record the incident{RESET}  {DIM}(ungated tool, live run){RESET}")
    with chronicle.record("deletion-incident", export=str(trace)):
        run(delete_file_ungated)
    print(f"   agent@1 -> delete_file@1   {RED}deleted production data{RESET}")
    print(f"   {DIM}frozen as a fixture{RESET}\n")

    print(f"{BOLD}2. Cut-point test{RESET}  {DIM}(stub the model, run the gated fix live){RESET}")
    with chronicle.replay_trace(
        str(trace),
        ReplayPlan().stub("agent", 1).live("delete_file", 1),
    ) as session:
        run(delete_file_gated)
        blocked = session.captured_result("delete_file", 1)["blocked"]

    verdict = f"{GREEN}PASS{RESET}" if blocked else f"{RED}FAIL{RESET}"
    print(f"   delete_file@1 blocked in production   [{verdict}]   {DIM}no LLM call{RESET}\n")
    print(f"{GREEN}The incident is now a committed regression test.{RESET}")


if __name__ == "__main__":
    main()
