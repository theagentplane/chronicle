"""
Scenario 24: Dollar notional confused with share quantity.

User asks to sell ~$1,000 of ACME. Agent sells 1,000 shares (~$190k).
"""

from __future__ import annotations

from typing import Any

from chronicle.boundary import boundary
from chronicle.envelope.schema import InputState, ToolCall

from examples.financial_incidents._helpers import agent_input, fmt_usd

_mode = "ungated"

NAME = "trade-notional"
TRACE_ID = "trace-trade-notional-001"
TOOL = "place_order"
SYMBOL = "ACME"
SHARE_PRICE_CENTS = 19_000  # $190.00
INTENDED_NOTIONAL_CENTS = 100_000  # $1,000
MAX_ORDER_NOTIONAL_CENTS = 500_000  # $5,000 — gated tool refuses above this
BAD_QUANTITY = 1000  # shares — agent mistake
USER_MESSAGE = "Sell about $1,000 of ACME from my portfolio to rebalance."


def set_mode(mode: str) -> None:
    global _mode
    if mode not in ("ungated", "gated"):
        raise ValueError("mode must be 'ungated' or 'gated'")
    _mode = mode


def _order_input(*args, **kwargs) -> InputState:
    symbol = args[0] if args else kwargs["symbol"]
    quantity = args[1] if len(args) > 1 else kwargs["quantity"]
    side = kwargs.get("side", "sell")
    implied = quantity * SHARE_PRICE_CENTS
    return InputState(
        messages=[],
        graph_state={
            "symbol": symbol,
            "quantity": quantity,
            "side": side,
            "share_price_cents": SHARE_PRICE_CENTS,
            "intended_notional_cents": INTENDED_NOTIONAL_CENTS,
            "implied_notional_cents": implied,
            "max_order_notional_cents": MAX_ORDER_NOTIONAL_CENTS,
        },
    )


@boundary(TOOL, kind="tool", extract_input=_order_input)
def place_order(symbol: str, quantity: int, *, side: str = "sell") -> dict[str, Any]:
    """Order tool — gated version enforces a max order notional."""
    notional_cents = quantity * SHARE_PRICE_CENTS
    if _mode == "gated" and notional_cents > MAX_ORDER_NOTIONAL_CENTS:
        return {
            "status": "blocked",
            "blocked": True,
            "symbol": symbol,
            "quantity": quantity,
            "side": side,
            "notional_cents": notional_cents,
            "max_order_notional_cents": MAX_ORDER_NOTIONAL_CENTS,
            "message": (
                f"Order blocked — {fmt_usd(notional_cents)} exceeds "
                f"maximum {fmt_usd(MAX_ORDER_NOTIONAL_CENTS)}"
            ),
        }
    return {
        "status": "filled",
        "blocked": False,
        "symbol": symbol,
        "quantity": quantity,
        "side": side,
        "fill_price_cents": SHARE_PRICE_CENTS,
        "notional_cents": notional_cents,
        "message": (
            f"Sold {quantity} {symbol} at {fmt_usd(SHARE_PRICE_CENTS)} "
            f"({fmt_usd(notional_cents)} total)"
        ),
    }


@boundary("agent", kind="llm", extract_input=agent_input)
def agent_plan(state: dict[str, Any]) -> dict[str, Any]:
    """Simulated LLM — treats '$1,000' as 1,000 shares."""
    tool_call = ToolCall(
        id="call_order_1",
        name=TOOL,
        arguments={"symbol": SYMBOL, "quantity": BAD_QUANTITY, "side": "sell"},
    )
    return {
        **state,
        "tool_calls": [tool_call.model_dump()],
        "completion": f"I'll sell {fmt_usd(INTENDED_NOTIONAL_CENTS)} worth of {SYMBOL}.",
        "finish_reason": "tool_calls",
    }


@boundary("agent", kind="llm", extract_input=agent_input)
def agent_finalize(state: dict[str, Any], tool_result: dict[str, Any]) -> dict[str, Any]:
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
        "filled": tool_result.get("status") == "filled",
        "blocked": tool_result.get("blocked", False),
    }


def run_agent(user_message: str = USER_MESSAGE) -> dict[str, Any]:
    state: dict[str, Any] = {
        "messages": [{"role": "user", "content": user_message}],
        "user_message": user_message,
        "system_prompt": "You are a portfolio management agent.",
        "intended_notional_cents": INTENDED_NOTIONAL_CENTS,
        "tool_calls": [],
        "completion": "",
        "finish_reason": "",
        "filled": False,
        "blocked": False,
    }
    state = agent_plan(state)
    tool_result = place_order(SYMBOL, BAD_QUANTITY, side="sell")
    return agent_finalize(state, tool_result)
