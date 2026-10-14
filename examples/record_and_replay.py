"""Record an incident, then test the fix by replaying it: no model call, no new spend.

An operations agent is asked to clean up logs. The model decides which file to delete and the
tool deletes it in production: that is the incident. The request is saved to the control plane.
The fix (a guard in the tool) is then tested by replaying the saved request with the model's
recorded answer and only the tool running live.

    OPENAI_API_KEY=... python examples/record_and_replay.py
"""

import json
from typing import Any

import chronicle
from _support.llm import OPENAI_MODEL, openai_client
from _support.plane import LocalPlane
from _support.show import show_trace
from chronicle import ReplayPlan

SYSTEM = (
    "You are an operations assistant. Carry out cleanup requests with the delete_file tool. "
    "Always call the tool, then say what you did in one sentence."
)
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a file. environment is 'prod' or 'staging'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "environment": {"type": "string", "enum": ["prod", "staging"]},
                },
                "required": ["path", "environment"],
            },
        },
    }
]
REQUEST = "Clean up the old application log /var/log/app/app.log in production."

GATED = False  # the fix: refuse to delete in production
DELETED: list[str] = []  # the "disk": nothing real is touched


@chronicle.boundary("delete_file", kind="tool")
def delete_file(path: str, environment: str) -> dict[str, Any]:
    if GATED and environment == "prod":
        return {"blocked": True, "deleted": False, "reason": "production deletes need approval"}
    DELETED.append(f"{environment}:{path}")
    return {"blocked": False, "deleted": True, "path": path}


def run_agent(client: Any, request: str) -> str:
    """A model-and-tool loop. The same code runs when recording and when replaying."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": request},
    ]
    for _ in range(4):
        reply = client.chat.completions.create(model=OPENAI_MODEL, messages=messages, tools=TOOLS)
        message = reply.choices[0].message
        if not message.tool_calls:
            return str(message.content or "")
        messages.append(message.model_dump(exclude_none=True))
        for call in message.tool_calls:
            result = delete_file(**json.loads(call.function.arguments))
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)}
            )
    return "gave up"


def main() -> None:
    global GATED
    client = openai_client()
    with LocalPlane(service_name="ops-agent") as plane:
        print("1. RECORD the incident (live model, unguarded tool)\n")
        with chronicle.record("deletion-incident", labels={"demo": "record-and-replay"}) as session:
            answer = run_agent(client, REQUEST)
        trace_id, span_id = session.trace_id, session.span_id
        print(f"agent said: {answer}")
        print(f"deleted:    {DELETED}\n")
        trace = plane.wait_for_spans(trace_id, 1)
        show_trace(plane, trace["trace_id"])
        if not DELETED:
            raise SystemExit("The model did not call delete_file; run the demo again.")

        print("\n2. REPLAY with the fix: model answer stubbed, only delete_file runs live\n")
        GATED = True
        DELETED.clear()
        plan = ReplayPlan().run("delete_file", 1)
        with chronicle.replay_trace(trace_id, span_id, plan) as run:
            replayed = run_agent(client, REQUEST)
        result = run.captured_result("delete_file", 1)
        print(f"agent said: {replayed}")
        print(f"tool result: {result}")
        print(f"deleted:     {DELETED}")
        assert result["blocked"] is True, "the fix did not hold"
        assert not DELETED, "the fix did not hold"
        print("\nThe guard blocks the same call the model made, with no new model call.")


if __name__ == "__main__":
    main()
