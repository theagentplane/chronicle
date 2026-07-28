#!/usr/bin/env python3
"""Evaluation harness for the Chronicle incident benchmark.

Produces the numbers the paper reports:

- Recording overhead: the compute cost of recording a run (in-memory, excludes the
  optional disk flush), reported in microseconds per crossing and as a fraction of a
  typical model call. Recording is a fixed per-crossing cost; against a real model call
  (hundreds of ms) it is negligible.
- Store growth: bytes written to the append-only store per recorded crossing.
- Replay determinism: N full-stub replays reproduce the run with zero live crossings
  (zero model calls).
- Detection: the cut-point test fails on the unguarded incident.
- Specificity: it passes on the guarded fix and on a benign unrelated change.

Run:

    python -m examples.benchmark.harness
    python -m examples.benchmark.harness --json out.json --tex table.tex
    python -m examples.benchmark.harness --model-latency-ms 500

Every scenario uses simulated (recorded) boundaries, so the whole suite makes zero real
model calls and runs deterministically in CI.
"""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from types import ModuleType

from chronicle.envelope.store import EnvelopeStore
from chronicle.replay.plan import ReplayPlan
from chronicle.session import reset_session
from examples.financial_incidents import (
    email_blast,
    invoice_currency,
    payout_injection,
    prod_delete,
    refund_order_id,
    trade_notional,
)

# Display name -> scenario module. Order matches the paper's Table 1.
SCENARIOS: dict[str, ModuleType] = {
    "Refund": refund_order_id,
    "Invoice": invoice_currency,
    "Trade": trade_notional,
    "Email": email_blast,
    "Payout": payout_injection,
    "Deletion": prod_delete,
}

REPS = 500  # timing repetitions per measurement
ROUNDS = 7  # take the best (min) of this many rounds
REPLAYS = 20  # determinism: replay the run this many times
MODEL_LATENCY_MS = 300.0  # a typical single model call, for the overhead projection


@dataclass
class ScenarioResult:
    name: str
    crossings: int
    t_base_us: float  # raw app logic, no recording
    t_rec_us: float  # in-memory recording of the run
    overhead_us_per_crossing: float  # recording compute cost per crossing
    overhead_pct_at_model: float  # that cost as % of one MODEL_LATENCY_MS call
    bytes_per_crossing: float
    replay_live_crossings: int  # live crossings during full-stub replay (model calls)
    deterministic: bool
    detected: bool  # unguarded -> test fails
    spec_gated: bool  # gated -> test passes
    spec_benign: bool  # benign -> test passes


# --- zero-instrumentation baseline via __wrapped__ --------------------------------- #
def _patch_raw(mod: ModuleType) -> dict[str, object]:
    """Swap every @boundary-decorated function in the module for its raw __wrapped__,
    so a baseline run pays no recording cost. Returns the originals to restore."""
    originals: dict[str, object] = {}
    for name, val in list(vars(mod).items()):
        if callable(val) and hasattr(val, "__wrapped__"):
            originals[name] = val
            setattr(mod, name, val.__wrapped__)
    return originals


def _restore(mod: ModuleType, originals: dict[str, object]) -> None:
    for name, val in originals.items():
        setattr(mod, name, val)


def _best_time(fn, reps: int = REPS, rounds: int = ROUNDS) -> float:
    """Best (min) average seconds per call over several rounds. Warms up first."""
    for _ in range(min(reps, 50)):
        fn()
    best = float("inf")
    for _ in range(rounds):
        start = perf_counter()
        for _ in range(reps):
            fn()
        best = min(best, (perf_counter() - start) / reps)
    return best


# --- measurements ------------------------------------------------------------------ #
def _record_incident(mod: ModuleType, workdir: Path) -> tuple[Path, int, int]:
    """Record the ungated incident to disk. Returns (trace_dir, crossings, store_bytes)."""
    mod.set_mode("ungated")
    store_path = workdir / f"{mod.NAME}.jsonl"
    session = reset_session()
    session.build_id = f"bench-{mod.NAME}"
    session.store = EnvelopeStore(store_path)
    session.begin_trace(mod.TRACE_ID)
    mod.run_agent()
    trace_dir = workdir / mod.NAME
    session.export_trace(trace_dir)
    crossings = len(session._recorded_envelopes)
    return trace_dir, crossings, store_path.stat().st_size


def _measure_overhead(mod: ModuleType) -> tuple[float, float]:
    """Return (t_base, t_rec) seconds per run: raw app logic vs in-memory recording.

    Recording is measured in memory (store=None) so this is the instrumentation compute
    cost, not disk I/O. Store growth is measured separately in _record_incident."""
    mod.set_mode("ungated")

    originals = _patch_raw(mod)
    try:
        t_base = _best_time(mod.run_agent)
    finally:
        _restore(mod, originals)

    def rec() -> None:
        session = reset_session()
        session.store = None  # in-memory recording only
        session.begin_trace(mod.TRACE_ID)
        mod.run_agent()

    t_rec = _best_time(rec)
    return t_base, t_rec


def _replay_determinism(mod: ModuleType, trace_dir: Path) -> tuple[bool, int]:
    """Full-stub replay REPLAYS times. Returns (all identical, live crossings)."""
    outcomes: list[str] = []
    live_crossings = 0
    for i in range(REPLAYS):
        mod.set_mode("gated")  # code present but never runs under full stub
        session = reset_session()
        session.load_trace(trace_dir)
        session.enable_replay(ReplayPlan())  # stub everything
        result = mod.run_agent(user_message="stubbed")
        if i == 0:
            live_crossings = sum(1 for c in session.call_log() if c.mode == "live")
        outcomes.append(json.dumps(result.get("completion", "")) + str(result.get("blocked")))
    return len(set(outcomes)) == 1, live_crossings


def _cutpoint_safe(mod: ModuleType, trace_dir: Path, variant: str) -> bool:
    """Run the cut-point test against a tool variant; return whether the safety
    invariant held (test passed)."""
    mod.set_mode(variant)
    session = reset_session()
    session.load_trace(trace_dir)
    plan = ReplayPlan().stub("agent", 1).live(mod.TOOL, 1).live("agent", 2)
    session.enable_replay(plan)
    result = mod.run_agent(user_message="stubbed")
    live = session.captured_result(mod.TOOL, 1) or {}
    return mod.safe(result, live)


def evaluate(name: str, mod: ModuleType, workdir: Path) -> ScenarioResult:
    trace_dir, crossings, store_bytes = _record_incident(mod, workdir)
    t_base, t_rec = _measure_overhead(mod)
    deterministic, live_crossings = _replay_determinism(mod, trace_dir)

    ungated_safe = _cutpoint_safe(mod, trace_dir, "ungated")
    spec_gated = _cutpoint_safe(mod, trace_dir, "gated")
    spec_benign = _cutpoint_safe(mod, trace_dir, "benign")

    overhead_us = (t_rec - t_base) * 1e6
    per_crossing_us = overhead_us / crossings if crossings else 0.0
    pct_at_model = per_crossing_us / (MODEL_LATENCY_MS * 1000.0) * 100.0
    return ScenarioResult(
        name=name,
        crossings=crossings,
        t_base_us=t_base * 1e6,
        t_rec_us=t_rec * 1e6,
        overhead_us_per_crossing=per_crossing_us,
        overhead_pct_at_model=pct_at_model,
        bytes_per_crossing=store_bytes / crossings if crossings else 0.0,
        replay_live_crossings=live_crossings,
        deterministic=deterministic,
        detected=not ungated_safe,
        spec_gated=spec_gated,
        spec_benign=spec_benign,
    )


# --- reporting --------------------------------------------------------------------- #
def run_all() -> list[ScenarioResult]:
    results: list[ScenarioResult] = []
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for name, mod in SCENARIOS.items():
            results.append(evaluate(name, mod, workdir))
    return results


def print_table(results: list[ScenarioResult]) -> None:
    print()
    print(f"  {'Scenario':<9} {'cross':>5} {'t_base':>9} {'t_rec':>9} {'rec/cross':>10} "
          f"{'%@model':>8} {'B/cross':>8} {'replay':>7} {'detect':>7} {'spec':>5}")
    print("  " + "-" * 90)
    for r in results:
        spec = "yes" if (r.spec_gated and r.spec_benign) else "NO"
        print(f"  {r.name:<9} {r.crossings:>5} {r.t_base_us:>8.1f}u {r.t_rec_us:>8.1f}u "
              f"{r.overhead_us_per_crossing:>9.1f}u {r.overhead_pct_at_model:>7.3f}% "
              f"{r.bytes_per_crossing:>8.0f} {r.replay_live_crossings:>7} "
              f"{'yes' if r.detected else 'NO':>7} {spec:>5}")
    print("  " + "-" * 90)
    n = len(results)
    det = sum(r.detected for r in results)
    spec = sum(r.spec_gated and r.spec_benign for r in results)
    total_replay_calls = sum(r.replay_live_crossings for r in results)
    all_det = all(r.deterministic for r in results)
    med_us = statistics.median(r.overhead_us_per_crossing for r in results)
    med_pct = statistics.median(r.overhead_pct_at_model for r in results)
    max_kb = max(r.bytes_per_crossing for r in results) / 1024.0
    print(f"\n  incidents (N)          : {n}")
    print(f"  detection rate         : {det}/{n} incidents flagged")
    print(f"  specificity            : {spec}/{n} pass on guarded + benign")
    print(f"  replay model calls     : {total_replay_calls}  (full-stub replay of all)")
    print(f"  deterministic replay   : {'yes' if all_det else 'NO'}  ({REPLAYS} replays each)")
    print(f"  recording overhead     : {med_us:.1f} us / crossing "
          f"(= {med_pct:.3f}% of a {MODEL_LATENCY_MS:.0f} ms model call)")
    print(f"  store growth           : <= {max_kb:.2f} KB / crossing")
    print()


def to_latex(results: list[ScenarioResult]) -> str:
    n = len(results)
    det = sum(r.detected for r in results)
    spec = sum(r.spec_gated and r.spec_benign for r in results)
    med_us = statistics.median(r.overhead_us_per_crossing for r in results)
    med_pct = statistics.median(r.overhead_pct_at_model for r in results)
    max_kb = max(r.bytes_per_crossing for r in results) / 1024.0
    lines = [
        "% Auto-generated by examples/benchmark/harness.py",
        "\\newcommand{\\numincidents}{%d}" % n,
        "\\newcommand{\\detectionrate}{%d/%d}" % (det, n),
        "\\newcommand{\\specificity}{%d/%d}" % (spec, n),
        "\\newcommand{\\recoverheadus}{%.1f}" % med_us,
        "\\newcommand{\\recoverheadpct}{%.3f}" % med_pct,
        "\\newcommand{\\kbpercrossing}{%.2f}" % max_kb,
        "\\newcommand{\\modellatencyms}{%.0f}" % MODEL_LATENCY_MS,
        "",
        "\\begin{table}[t]",
        "\\centering",
        "\\small",
        "\\begin{tabular}{lrrrr}",
        "\\toprule",
        "Scenario & Cross. & $t_{\\mathrm{base}}$ & $t_{\\mathrm{rec}}$ & "
        "Rec./cross. \\\\",
        " & & (\\textmu s) & (\\textmu s) & (\\textmu s) \\\\",
        "\\midrule",
    ]
    for r in results:
        lines.append(
            f"{r.name} & {r.crossings} & {r.t_base_us:.1f} & {r.t_rec_us:.1f} & "
            f"{r.overhead_us_per_crossing:.1f} \\\\"
        )
    lines += [
        "\\bottomrule",
        "\\end{tabular}",
        "\\caption{Recording adds \\recoverheadus{}~\\textmu s per crossing "
        "(\\recoverheadpct\\% of a \\modellatencyms~ms model call). Replaying the suite "
        "makes zero model calls; cut-point tests flag \\detectionrate{} incidents and "
        "pass on \\specificity{} guarded and benign changes. The store grows by at most "
        "\\kbpercrossing{}~KB per crossing.}",
        "\\label{tab:overhead}",
        "\\end{table}",
    ]
    return "\n".join(lines)


def main() -> None:
    global MODEL_LATENCY_MS
    parser = argparse.ArgumentParser(description="Chronicle incident benchmark harness")
    parser.add_argument("--json", type=Path, help="write raw results as JSON")
    parser.add_argument("--tex", type=Path, help="write a LaTeX table + macros")
    parser.add_argument("--model-latency-ms", type=float, default=MODEL_LATENCY_MS,
                        help="typical model-call latency for the overhead projection")
    args = parser.parse_args()
    MODEL_LATENCY_MS = args.model_latency_ms

    results = run_all()
    print_table(results)

    if args.json:
        args.json.write_text(json.dumps([asdict(r) for r in results], indent=2), encoding="utf-8")
        print(f"  wrote {args.json}")
    if args.tex:
        args.tex.write_text(to_latex(results), encoding="utf-8")
        print(f"  wrote {args.tex}")


if __name__ == "__main__":
    main()
