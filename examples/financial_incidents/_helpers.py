"""Shared helpers for financial incident demos."""

from __future__ import annotations

import os
import sys

from chronicle.envelope.schema import Envelope, InputState

# ANSI colors — disabled for pipes, CI, and NO_COLOR
_USE_COLOR = (
    sys.stdout.isatty()
    and os.environ.get("NO_COLOR") is None
    and os.environ.get("TERM", "") != "dumb"
)


def _c(code: str, text: str) -> str:
    if not _USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def color(text: str, role: str) -> str:
    roles = {
        "title": "1;36",      # bold cyan
        "label": "2",         # dim
        "value": "0",
        "bad": "1;31",        # bold red — incident outcomes
        "good": "1;32",       # bold green — blocked / pass
        "warn": "1;33",       # bold yellow — amounts, LIVE
        "muted": "2;37",      # dim white
        "fail": "1;31",
        "pass": "1;32",
        "stub": "36",         # cyan
        "live": "1;33",       # bold yellow
    }
    return _c(roles.get(role, "0"), text)


def set_color_enabled(enabled: bool) -> None:
    global _USE_COLOR
    _USE_COLOR = enabled


def agent_input(*args, **kwargs) -> InputState:
    state = args[0] if args else kwargs.get("state", {})
    if not isinstance(state, dict):
        state = {}
    graph_state = dict(state)
    if len(args) > 1 and isinstance(args[1], dict):
        graph_state["tool_result"] = args[1]
    return InputState(
        messages=state.get("messages", []),
        system_prompt=state.get("system_prompt"),
        graph_state=graph_state,
    )


def fmt_usd(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def fmt_eur(cents: int) -> str:
    return f"€{cents / 100:,.2f}"


def truncate(text: str, max_len: int = 36) -> str:
    text = normalize(text)
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def normalize(text: str) -> str:
    return " ".join(str(text).split())


def summarize_llm_input(inp: InputState) -> str:
    if inp.messages:
        return truncate(inp.messages[-1].get("content", ""))
    return truncate(inp.graph_state.get("user_message", ""))


def summarize_tool_input(inp: InputState) -> str:
    gs = inp.graph_state
    parts: list[str] = []
    for key, value in gs.items():
        if key in ("args", "kwargs", "implied_notional_cents"):
            continue
        if key.endswith("_cents") and isinstance(value, int):
            parts.append(f"{key}={fmt_usd(value)}")
        else:
            parts.append(f"{key}={value}")
    return truncate(", ".join(parts))


def summarize_envelope_input(env: Envelope) -> str:
    if env.boundary_kind == "llm" and env.invocation_index > 1:
        tool_result = env.input_state.graph_state.get("tool_result")
        if tool_result:
            return truncate(f"tool_result: {tool_result.get('status', tool_result)}")
    if env.boundary_kind == "llm":
        return summarize_llm_input(env.input_state)
    return summarize_tool_input(env.input_state)


def _fmt_arg(key: str, value: object) -> str:
    if key.endswith("_cents") and isinstance(value, int):
        return f"{key}={fmt_usd(value)}"
    return f"{key}={value}"


def summarize_envelope_output(env: Envelope) -> str:
    action = env.action_result
    if action.tool_calls:
        call = action.tool_calls[0]
        args = ", ".join(_fmt_arg(k, v) for k, v in call.arguments.items())
        return normalize(f"→ {call.name}({args})")
    if action.raw_response:
        raw = action.raw_response
        status = raw.get("status", "")
        message = raw.get("message", "")
        if message:
            return normalize(f"{status}: {message}")
        return normalize(str(raw))
    if action.completion:
        return normalize(action.completion)
    return "—"


def summarize_dict_output(data: dict) -> str:
    status = data.get("status", "")
    message = data.get("message", "")
    if message:
        return normalize(f"{status}: {message}")
    return normalize(str(data))


BoundaryRow = tuple[str, str, str, str, str]  # node, kind, mode, input, output


def print_boundary_table(rows: list[BoundaryRow]) -> None:
    widths = (18, 5, 6, 38)
    headers = ("Node", "Kind", "Mode", "Input", "Output")

    def fmt_row(node: str, kind: str, mode: str, inp: str, out: str) -> str:
        main = "  " + " ".join(
            cell[:w].ljust(w) for cell, w in zip((node, kind, mode, inp), widths)
        )
        return f"{main} {out}"

    print(fmt_row(*headers))
    print("  " + "─" * 70)
    for row in rows:
        print(fmt_row(*row))
