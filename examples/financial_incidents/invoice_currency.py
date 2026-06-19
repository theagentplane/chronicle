"""
Scenario 8: Invoice currency mismatch.

User asks for a €2M invoice. Agent uses the correct amount but wrong currency (USD).
"""

from __future__ import annotations

from typing import Any

from chronicle.boundary import boundary
from chronicle.envelope.schema import InputState, ToolCall

from examples.financial_incidents._helpers import agent_input, fmt_eur, fmt_usd

_mode = "ungated"

NAME = "invoice-currency"
TRACE_ID = "trace-invoice-currency-001"
TOOL = "create_invoice"
CUSTOMER_ID = "acme-corp"
AMOUNT_CENTS = 200_000_000  # €2,000,000
MAX_INVOICE_CENTS = 10_000_000  # $100,000 — gated tool refuses above this
CONTRACT_CURRENCY = "EUR"
USER_MESSAGE = "Send Acme Corp the annual platform invoice — €2,000,000 per the signed SOW."


def set_mode(mode: str) -> None:
    global _mode
    if mode not in ("ungated", "gated"):
        raise ValueError("mode must be 'ungated' or 'gated'")
    _mode = mode


def _invoice_input(*args, **kwargs) -> InputState:
    if args and isinstance(args[0], dict):
        graph_state = dict(args[0])
    else:
        graph_state = {
            "customer_id": kwargs.get("customer_id", args[0] if args else ""),
            "amount_cents": kwargs.get("amount_cents", args[1] if len(args) > 1 else 0),
            "currency": kwargs.get("currency", args[2] if len(args) > 2 else ""),
        }
    graph_state.setdefault("contract_currency", CONTRACT_CURRENCY)
    graph_state.setdefault("contract_amount_cents", AMOUNT_CENTS)
    graph_state.setdefault("max_invoice_cents", MAX_INVOICE_CENTS)
    return InputState(messages=[], graph_state=graph_state)


@boundary(TOOL, kind="tool", extract_input=_invoice_input)
def create_invoice(customer_id: str, amount_cents: int, currency: str) -> dict[str, Any]:
    """Invoice tool — gated version enforces a max invoice amount."""
    if _mode == "gated" and amount_cents > MAX_INVOICE_CENTS:
        return {
            "status": "blocked",
            "blocked": True,
            "customer_id": customer_id,
            "amount_cents": amount_cents,
            "currency": currency,
            "max_invoice_cents": MAX_INVOICE_CENTS,
            "message": (
                f"Invoice blocked — {fmt_usd(amount_cents)} exceeds "
                f"maximum {fmt_usd(MAX_INVOICE_CENTS)}"
            ),
        }
    return {
        "status": "sent",
        "blocked": False,
        "customer_id": customer_id,
        "amount_cents": amount_cents,
        "currency": currency,
        "contract_currency": CONTRACT_CURRENCY,
        "message": f"Invoice sent to {customer_id} for {amount_cents / 100:,.2f} {currency}",
    }


@boundary("agent", kind="llm", extract_input=agent_input)
def agent_plan(state: dict[str, Any]) -> dict[str, Any]:
    """Simulated LLM — correct amount, wrong currency."""
    tool_call = ToolCall(
        id="call_invoice_1",
        name=TOOL,
        arguments={
            "customer_id": CUSTOMER_ID,
            "amount_cents": AMOUNT_CENTS,
            "currency": "USD",
        },
    )
    return {
        **state,
        "tool_calls": [tool_call.model_dump()],
        "completion": f"I'll send the {fmt_eur(AMOUNT_CENTS)} invoice to Acme Corp.",
        "finish_reason": "tool_calls",
    }


@boundary("agent", kind="llm", extract_input=agent_input)
def agent_finalize(state: dict[str, Any], tool_result: dict[str, Any]) -> dict[str, Any]:
    if tool_result.get("blocked"):
        completion = tool_result["message"]
    else:
        amt = tool_result["amount_cents"]
        cur = tool_result["currency"]
        sym = "$" if cur == "USD" else "€"
        completion = f"Invoice sent to Acme Corp for {sym}{amt / 100:,.2f} {cur}."

    return {
        **state,
        "tool_result": tool_result,
        "tool_calls": [],
        "completion": completion,
        "finish_reason": "stop",
        "invoice_sent": tool_result.get("status") == "sent",
        "blocked": tool_result.get("blocked", False),
    }


def run_agent(user_message: str = USER_MESSAGE) -> dict[str, Any]:
    state: dict[str, Any] = {
        "messages": [{"role": "user", "content": user_message}],
        "user_message": user_message,
        "system_prompt": "You are an enterprise billing agent.",
        "contract_currency": CONTRACT_CURRENCY,
        "tool_calls": [],
        "completion": "",
        "finish_reason": "",
        "invoice_sent": False,
        "blocked": False,
    }
    state = agent_plan(state)
    tool_result = create_invoice(CUSTOMER_ID, AMOUNT_CENTS, "USD")
    return agent_finalize(state, tool_result)
