"""
Scenario 1: Refund amount mistaken for order ID.

User asks to refund a $47 order. Agent passes the order ID digits as the amount.
"""

from __future__ import annotations

from typing import Any

from chronicle.boundary import boundary
from chronicle.envelope.schema import InputState, ToolCall

from examples.financial_incidents._helpers import agent_input, fmt_usd

# ungated = record incident | gated = cut-point fix
_mode = "ungated"

NAME = "refund-order-id"
TRACE_ID = "trace-refund-order-id-001"
TOOL = "issue_refund"
ORDER_ID = "9847261"
ORDER_TOTAL_CENTS = 4_700  # $47.00
MAX_REFUND_CENTS = 1_000_000  # $10,000 — gated tool refuses above this
BAD_AMOUNT_CENTS = int(ORDER_ID) * 100  # agent used order ID digits as dollars
USER_MESSAGE = "Refund order #9847261 — customer was double charged on the $47 plan."


def set_mode(mode: str) -> None:
    global _mode
    if mode not in ("ungated", "gated"):
        raise ValueError("mode must be 'ungated' or 'gated'")
    _mode = mode


def _refund_input(*args, **kwargs) -> InputState:
    order_id = args[0] if args else kwargs["order_id"]
    amount_cents = args[1] if len(args) > 1 else kwargs["amount_cents"]
    return InputState(
        messages=[],
        graph_state={
            "order_id": order_id,
            "amount_cents": amount_cents,
            "order_total_cents": ORDER_TOTAL_CENTS,
            "max_refund_cents": MAX_REFUND_CENTS,
        },
    )


@boundary(TOOL, kind="tool", extract_input=_refund_input)
def issue_refund(order_id: str, amount_cents: int) -> dict[str, Any]:
    """Refund tool — gated version enforces a max refund amount."""
    if _mode == "gated" and amount_cents > MAX_REFUND_CENTS:
        return {
            "status": "blocked",
            "blocked": True,
            "order_id": order_id,
            "amount_cents": amount_cents,
            "max_refund_cents": MAX_REFUND_CENTS,
            "message": (
                f"Refund blocked — {fmt_usd(amount_cents)} exceeds "
                f"maximum {fmt_usd(MAX_REFUND_CENTS)}"
            ),
        }
    return {
        "status": "refunded",
        "blocked": False,
        "order_id": order_id,
        "amount_cents": amount_cents,
        "order_total_cents": ORDER_TOTAL_CENTS,
        "message": f"Refunded {fmt_usd(amount_cents)} to order #{order_id}",
    }


@boundary("agent", kind="llm", extract_input=agent_input)
def agent_plan(state: dict[str, Any]) -> dict[str, Any]:
    """Simulated LLM — mistakenly uses order ID as refund amount."""
    tool_call = ToolCall(
        id="call_refund_1",
        name=TOOL,
        arguments={"order_id": ORDER_ID, "amount_cents": BAD_AMOUNT_CENTS},
    )
    return {
        **state,
        "tool_calls": [tool_call.model_dump()],
        "completion": f"I'll process the refund for order #{ORDER_ID} now.",
        "finish_reason": "tool_calls",
    }


@boundary("agent", kind="llm", extract_input=agent_input)
def agent_finalize(state: dict[str, Any], tool_result: dict[str, Any]) -> dict[str, Any]:
    """Simulated LLM — reports refund outcome to the user."""
    if tool_result.get("blocked"):
        completion = tool_result["message"]
    else:
        completion = f"Done. {tool_result['message']}"

    return {
        **state,
        "tool_result": tool_result,
        "tool_calls": [],
        "completion": completion,
        "finish_reason": "stop",
        "refunded": tool_result.get("status") == "refunded",
        "blocked": tool_result.get("blocked", False),
    }


def run_agent(user_message: str = USER_MESSAGE) -> dict[str, Any]:
    state: dict[str, Any] = {
        "messages": [{"role": "user", "content": user_message}],
        "user_message": user_message,
        "system_prompt": "You are a billing support agent.",
        "tool_calls": [],
        "completion": "",
        "finish_reason": "",
        "refunded": False,
        "blocked": False,
    }
    state = agent_plan(state)
    tool_result = issue_refund(ORDER_ID, BAD_AMOUNT_CENTS)
    return agent_finalize(state, tool_result)
