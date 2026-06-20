#!/usr/bin/env python3
"""Run financial incident demos: record incidents and cut-point test."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from chronicle.envelope.store import EnvelopeStore
from chronicle.replay.plan import ReplayPlan
from chronicle.session import ChronicleSession, reset_session

from examples.financial_incidents import invoice_currency, refund_order_id, trade_notional
from examples.financial_incidents._helpers import (
    BoundaryRow,
    color,
    print_boundary_table,
    set_color_enabled,
    summarize_dict_output,
    summarize_envelope_input,
    summarize_envelope_output,
    summarize_tool_input,
    normalize,
)

FIXTURES = ROOT / "fixtures" / "traces"

SCENARIOS: dict[str, ModuleType] = {
    "refund": refund_order_id,
    "1": refund_order_id,
    "invoice": invoice_currency,
    "8": invoice_currency,
    "trade": trade_notional,
    "24": trade_notional,
}

ORDER = ["refund", "invoice", "trade"]


def _line(char: str = "─", width: int = 60) -> str:
    return f"  {char * width}"


def _header(title: str) -> None:
    print()
    print(color("=" * 62, "title"))
    print(color(f"  {title}", "title"))
    print(color("=" * 62, "title"))


def _label(text: str) -> str:
    return color(text, "label")


def _boundary_rows_from_record(session: ChronicleSession) -> list[BoundaryRow]:
    rows: list[BoundaryRow] = []
    for envelope in sorted(session._recorded_envelopes, key=lambda e: e.sequence):
        node = f"{envelope.node_id}@{envelope.invocation_index}"
        rows.append(
            (
                node,
                envelope.boundary_kind,
                "LIVE",
                summarize_envelope_input(envelope),
                summarize_envelope_output(envelope),
            )
        )
    return rows


def _boundary_rows_from_test(
    session: ChronicleSession,
    tool_label: str,
    result: dict,
) -> list[BoundaryRow]:
    graph = session.fixture_graph
    assert graph is not None

    agent1 = graph.envelope("agent", 1)
    rows: list[BoundaryRow] = [
        (
            "agent@1",
            "llm",
            "STUB",
            summarize_envelope_input(agent1),
            summarize_envelope_output(agent1),
        ),
    ]

    live_input = session.captured_input(tool_label, 1)
    live_output = session.captured_result(tool_label, 1)
    rows.append(
        (
            f"{tool_label}@1",
            "tool",
            "LIVE",
            summarize_tool_input(live_input) if live_input else "—",
            summarize_dict_output(live_output) if live_output else "—",
        ),
    )

    rows.append(
        (
            "agent@2",
            "llm",
            "LIVE",
            summarize_dict_output(live_output) if live_output else "—",
            normalize(result.get("completion", "")),
        ),
    )
    return rows


def _record(scenario: ModuleType) -> None:
    scenario.set_mode("ungated")

    session = reset_session()
    session.build_id = f"financial-demo-{scenario.NAME}"
    session.store = EnvelopeStore(ROOT / ".chronicle" / "runs" / f"{scenario.NAME}.jsonl")
    session.begin_trace(scenario.TRACE_ID)

    result = scenario.run_agent()

    trace_dir = FIXTURES / scenario.NAME
    session.export_trace(trace_dir)

    _header(f"RECORD  {scenario.NAME}")
    print(f"  {_label('User request')}     {scenario.USER_MESSAGE}")
    print()
    print(_line())
    print(f"  {color('Boundary results', 'title')}")
    print(_line())
    print_boundary_table(_boundary_rows_from_record(session))
    print()
    print(f"  {_label('Trace exported')}   {color(str(trace_dir.relative_to(ROOT)) + '/', 'good')}")
    print(color("=" * 62, "title"))


def _test(scenario: ModuleType) -> None:
    trace_dir = FIXTURES / scenario.NAME
    if not trace_dir.exists():
        print(f"No trace found at {trace_dir}. Run: record {scenario.NAME.split('-')[0]}")
        sys.exit(1)

    scenario.set_mode("gated")

    session = reset_session()
    session.load_trace(trace_dir)
    plan = ReplayPlan().stub("agent", 1).live(scenario.TOOL, 1).live("agent", 2)
    session.enable_replay(plan)

    result = scenario.run_agent(user_message="stubbed")

    live = session.captured_result(scenario.TOOL, 1)
    tool_label = scenario.TOOL

    _header(f"TEST  {scenario.NAME}  (cut-point)")
    print(_line())
    print(f"  {color('Boundary results', 'title')}")
    print(_line())
    print_boundary_table(_boundary_rows_from_test(session, tool_label, result))

    if scenario.NAME == "refund-order-id":
        checks = [
            ("refund blocked", live.get("blocked") is True),
            ("no money refunded", result.get("refunded") is False),
            ("agent@1 stubbed", session.call_log()[0].mode == "stub"),
            (f"{tool_label} ran live", any(c.mode == "live" and c.boundary_id == tool_label for c in session.call_log())),
        ]
    elif scenario.NAME == "invoice-currency":
        checks = [
            ("invoice blocked", live.get("blocked") is True),
            ("invoice not sent", result.get("invoice_sent") is False),
            ("agent@1 stubbed", session.call_log()[0].mode == "stub"),
            (f"{tool_label} ran live", any(c.mode == "live" and c.boundary_id == tool_label for c in session.call_log())),
        ]
    else:
        checks = [
            ("order blocked", live.get("blocked") is True),
            ("no shares sold", result.get("filled") is False),
            ("agent@1 stubbed", session.call_log()[0].mode == "stub"),
            (f"{tool_label} ran live", any(c.mode == "live" and c.boundary_id == tool_label for c in session.call_log())),
        ]

    print()
    print(_line())
    print(f"  {color('Verification', 'title')}")
    print(_line())

    all_pass = True
    for name, passed in checks:
        status = color("PASS", "pass") if passed else color("FAIL", "fail")
        print(f"  [{status}] {name}")
        all_pass = all_pass and passed

    print()
    print(f"  {_label('Final message')}    \"{result['completion']}\"")
    print(color("=" * 62, "title"))

    if not all_pass:
        sys.exit(1)


def _resolve(name: str) -> ModuleType:
    key = name.lower()
    if key not in SCENARIOS:
        valid = ", ".join(ORDER + ["all"])
        print(f"Unknown scenario: {name!r}. Choose: {valid}")
        sys.exit(1)
    return SCENARIOS[key]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Financial incident demos — record and cut-point test",
    )
    parser.add_argument(
        "scenario",
        help="refund (1) | invoice (8) | trade (24) | all",
    )
    parser.add_argument(
        "action",
        choices=["record", "test"],
        nargs="?",
        default="record",
        help="record incident or test gated fix (default: record)",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colors (also respects NO_COLOR env var)",
    )
    args = parser.parse_args()

    if args.no_color:
        set_color_enabled(False)

    if args.scenario.lower() == "all":
        for key in ORDER:
            mod = SCENARIOS[key]
            if args.action == "record":
                _record(mod)
            else:
                _test(mod)
        return

    mod = _resolve(args.scenario)
    if args.action == "record":
        _record(mod)
    else:
        _test(mod)


if __name__ == "__main__":
    main()
