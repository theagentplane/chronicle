"""Six costly agent mistakes: record each, then prove the fix by replaying it.

For every incident the agent plans a tool call (the planning mistake is deterministic so it
reproduces), runs the tool, and asks a live model to write the customer-facing message. The
request is saved to the control plane. The fix is a guard in the tool; it is tested by replaying
the saved request with the plan and the model call stubbed and only the tool running live.

    OPENAI_API_KEY=... python examples/incidents.py [refund-order-id invoice-currency ...]
"""

import json
import sys
from typing import Any

import chronicle
from _support.incident_cases import INCIDENTS, Incident
from _support.llm import OPENAI_MODEL, openai_client
from _support.plane import LocalPlane
from chronicle import ReplayPlan

GATED = False  # the fix is off while recording the incident


def build_agent(incident: Incident, client: Any) -> Any:
    """Return ``run(request) -> (message, tool_result)`` for one incident."""

    @chronicle.boundary("plan", kind="tool")
    def plan(request: str) -> dict[str, Any]:
        return dict(incident.arguments)  # the mistake: a fixed, wrong decision

    @chronicle.boundary(incident.tool, kind="tool")
    def act(arguments: dict[str, Any]) -> dict[str, Any]:
        reason = incident.guard(arguments) if GATED else None
        if reason:
            return {"blocked": True, incident.effect: False, "reason": reason}
        return {"blocked": False, incident.effect: True, **arguments}

    def run(request: str) -> tuple[str, dict[str, Any]]:
        result = act(plan(request))
        reply = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Write a one-sentence status update for the user."},
                {
                    "role": "user",
                    "content": f"Request: {request}\nTool result: {json.dumps(result)}",
                },
            ],
        )
        return str(reply.choices[0].message.content), result

    return run


def main() -> None:
    global GATED
    names = sys.argv[1:] or list(INCIDENTS)
    client = openai_client()
    outcomes: list[tuple[str, bool, bool]] = []
    with LocalPlane() as plane:
        for name in names:
            incident = INCIDENTS[name]
            run = build_agent(incident, client)

            GATED = False
            with chronicle.record(name, labels={"demo": "incident"}) as session:
                _message, result = run(incident.request)
            plane.wait_for_spans(session.trace_id, 1)
            damaged = bool(result.get(incident.effect))

            GATED = True
            plan = ReplayPlan().run(incident.tool, 1)
            with chronicle.replay_trace(session.trace_id, session.span_id, plan) as replayed:
                run(incident.request)
            fixed = replayed.captured_result(incident.tool, 1)
            held = bool(fixed["blocked"]) and not fixed[incident.effect]

            print(f"\n{name}: the agent {incident.mistake}")
            print(f"  recorded : {incident.tool}({incident.arguments}) -> {incident.effect}")
            print(f"  replayed : {fixed.get('reason', fixed)}")
            outcomes.append((name, damaged, held))

    print(f"\n{'incident':<20} {'damage recorded':<18} {'fix holds on replay'}")
    for name, damaged, held in outcomes:
        print(f"{name:<20} {'yes' if damaged else 'no':<18} {'PASS' if held else 'FAIL'}")
    if not all(held for _name, _damaged, held in outcomes):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
