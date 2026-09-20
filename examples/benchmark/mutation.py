#!/usr/bin/env python3
"""Full-mock baseline and mutation study for the incident benchmark.

Answers two reviewer questions for the camera-ready:

- Baseline: can a plan that stubs every boundary (the per-boundary-mock baseline)
  tell unguarded code from the guarded fix? The tool never runs under that plan, so
  its verdict should be the same for every code version.
- Mutation: first-order mutants of each guarded tool (relational, logical,
  condition-negation, operand-drop, and constant mutations). A mutant is killed when
  a test's verdict on it differs from that test's verdict on the unmutated fix.

Also times one full-stub pass and one cut-point pass over the whole suite.

Run:

    python -m examples.benchmark.mutation
    python -m examples.benchmark.mutation --json docs/mutation-results.json \
        --tex docs/mutation-table.tex
"""

from __future__ import annotations

import __future__
import argparse
import ast
import copy
import inspect
import json
import statistics
import tempfile
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import perf_counter
from types import ModuleType

from chronicle.replay.plan import ReplayPlan
from chronicle.session import reset_session
from examples.benchmark.harness import SCENARIOS

SUITE_ROUNDS = 20  # suite wall-clock: median of this many passes

# Relational operator replacement table (the standard ROR set).
_ROR: dict[type, tuple[type, ...]] = {
    ast.Gt: (ast.GtE, ast.Lt, ast.LtE, ast.Eq, ast.NotEq),
    ast.GtE: (ast.Gt, ast.Lt, ast.LtE, ast.Eq, ast.NotEq),
    ast.Lt: (ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq),
    ast.LtE: (ast.Lt, ast.Gt, ast.GtE, ast.Eq, ast.NotEq),
    ast.Eq: (ast.NotEq,),
    ast.NotEq: (ast.Eq,),
    ast.In: (ast.NotIn,),
    ast.NotIn: (ast.In,),
    ast.Is: (ast.IsNot,),
    ast.IsNot: (ast.Is,),
}


# --- mutant generation ------------------------------------------------------------- #
class _Mutator(ast.NodeTransformer):
    """Apply the ``target``-th mutation in a fixed walk order, or none (to count).

    Every candidate site contributes one or more alternatives. The walk order is
    deterministic, so index ``k`` always names the same mutant. f-string internals
    are skipped: they only shape message text, which the tests deliberately ignore.
    """

    def __init__(self, target: int = -1) -> None:
        self.target = target
        self.count = 0
        self.description = ""
        self.line = -1

    def _take(self) -> bool:
        hit = self.count == self.target
        self.count += 1
        return hit

    def _note(self, operator: str, node: ast.AST, before: str) -> None:
        self.line = getattr(node, "lineno", -1)
        self.description = f"{operator} L{self.line}: {before} -> {ast.unparse(node)}"

    def visit_JoinedStr(self, node: ast.JoinedStr) -> ast.AST:
        return node

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        self.generic_visit(node)
        for i, op in enumerate(node.ops):
            for alt in _ROR.get(type(op), ()):
                if self._take():
                    before = ast.unparse(node)
                    node.ops[i] = alt()
                    self._note("ROR", node, before)
        return node

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.AST:
        self.generic_visit(node)
        if self._take():
            before = ast.unparse(node)
            node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
            self._note("LCR", node, before)
            return node
        for i in range(len(node.values)):
            if self._take():
                before = ast.unparse(node)
                rest = node.values[:i] + node.values[i + 1:]
                new = rest[0] if len(rest) == 1 else ast.BoolOp(op=node.op, values=rest)
                ast.copy_location(new, node)
                self._note("drop-operand", new, before)
                return new
        return node

    def visit_If(self, node: ast.If) -> ast.AST:
        self.generic_visit(node)
        if self._take():
            before = ast.unparse(node.test)
            node.test = ast.copy_location(ast.UnaryOp(op=ast.Not(), operand=node.test), node.test)
            self._note("negate-cond", node.test, before)
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        value = node.value
        if isinstance(value, bool):
            alts: list[object] = [not value]
        elif isinstance(value, int):
            alts = [value + 1, value - 1]
        elif isinstance(value, str):
            alts = [f"XX{value}XX"]
        else:
            return node
        for alt in alts:
            if self._take():
                new = ast.copy_location(ast.Constant(value=alt), node)
                self._note("constant", new, ast.unparse(node))
                return new
        return node


def _tool_def(mod: ModuleType) -> ast.FunctionDef:
    """The function decorated with ``@boundary(TOOL, ...)``: the guarded tool under test."""
    tree = ast.parse(inspect.getsource(mod))
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            if (
                isinstance(dec, ast.Call)
                and getattr(dec.func, "id", None) == "boundary"
                and dec.args
                and getattr(dec.args[0], "id", None) == "TOOL"
            ):
                return node
    raise LookupError(f"no @boundary(TOOL) function in {mod.__name__}")


def _apply(fn: ast.FunctionDef, target: int) -> tuple[ast.FunctionDef, _Mutator]:
    """Return a copy of ``fn`` with mutation ``target`` applied (-1: count only).
    Only the body is mutated, never the decorator, signature, or docstring."""
    fn = copy.deepcopy(fn)
    mutator = _Mutator(target)
    body = fn.body
    has_doc = (
        bool(body)
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    )
    start = 1 if has_doc else 0
    fn.body = body[:start] + [mutator.visit(stmt) for stmt in body[start:]]
    return fn, mutator


def _install(mod: ModuleType, fn: ast.FunctionDef) -> None:
    """Rebind the tool in the module namespace to a freshly decorated mutant, so
    ``run_agent`` (which looks the tool up at call time) runs the mutant."""
    module = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    code = compile(
        module, inspect.getsourcefile(mod) or mod.__name__, "exec",
        flags=__future__.annotations.compiler_flag, dont_inherit=True,
    )
    exec(code, vars(mod))


# Where a surviving mutant sits in the guarded tool, derived from the tool's own AST.
_SURVIVOR_CATEGORIES = {
    "benign_branch": "benign-only branch (never runs for the fix)",
    "unguarded_path": "unguarded return (not reached on the recorded input)",
    "guard_still_blocks": "guard change that still blocks the recorded input",
    "ignored_field": "output field the assertion does not check",
}


def _regions(fn: ast.FunctionDef) -> dict[str, set[int]]:
    def lines(node: ast.AST) -> set[int]:
        return set(range(node.lineno, (node.end_lineno or node.lineno) + 1))

    guard = next(s for s in fn.body if isinstance(s, ast.If))
    benign = next((s for s in ast.walk(guard) if isinstance(s, ast.If) and s is not guard), None)
    unguarded = [s for s in fn.body if isinstance(s, ast.Return)][-1]
    return {
        "benign_branch": lines(benign) if benign is not None else set(),
        "unguarded_path": lines(unguarded),
        "guard_still_blocks": lines(guard.test),
    }


def _category(line: int, regions: dict[str, set[int]]) -> str:
    for name, span in regions.items():
        if line in span:
            return name
    return "ignored_field"


# --- tests under each plan ----------------------------------------------------------- #
def _cutpoint_plan(mod: ModuleType) -> ReplayPlan:
    return ReplayPlan().stub("agent", 1).live(mod.TOOL, 1).live("agent", 2)


def _cutpoint_passes(mod: ModuleType, trace_dir: Path) -> bool:
    """The paper's cut-point test: model stubbed, tool and finalize live."""
    session = reset_session()
    session.load_trace(trace_dir)
    session.enable_replay(_cutpoint_plan(mod))
    try:
        result = mod.run_agent(user_message="stubbed")
    except Exception:
        return False  # a crash is a failing test
    live = session.captured_result(mod.TOOL, 1) or {}
    return bool(mod.safe(result, live))


def _fullstub_passes(mod: ModuleType, trace_dir: Path) -> bool:
    """The per-boundary-mock baseline: every boundary returns its recorded output, and
    the same safety assertion is checked against the tool output the mock returned."""
    session = reset_session()
    session.load_trace(trace_dir)
    session.enable_replay(ReplayPlan())
    try:
        result = mod.run_agent(user_message="stubbed")
    except Exception:
        return False
    mocked = session.fixture_graph.envelope(mod.TOOL, 1).action_result.raw_response or {}
    return bool(mod.safe(result, mocked))


# --- evaluation -------------------------------------------------------------------- #
@dataclass
class IncidentResult:
    name: str
    model_crossings: int
    cutpoint_verdicts: dict[str, bool]  # code version -> test passed
    fullstub_verdicts: dict[str, bool]
    mutants: int
    killed_cutpoint: int
    killed_fullstub: int
    survivors: list[dict[str, str]] = field(default_factory=list)  # category, mutation


def _record(mod: ModuleType, workdir: Path) -> tuple[Path, int]:
    """Record the unguarded incident. Returns (trace_dir, model crossings)."""
    mod.set_mode("ungated")
    session = reset_session()
    session.build_id = f"mutation-{mod.NAME}"
    session.begin_trace(mod.TRACE_NAME)
    mod.run_agent()
    trace_dir = workdir / mod.NAME
    session.export_trace(trace_dir)
    model_crossings = sum(1 for e in session._recorded_envelopes if e.kind == "llm")
    return trace_dir, model_crossings


def evaluate(name: str, mod: ModuleType, workdir: Path) -> tuple[IncidentResult, Path]:
    trace_dir, model_crossings = _record(mod, workdir)

    cutpoint_verdicts: dict[str, bool] = {}
    fullstub_verdicts: dict[str, bool] = {}
    for variant in ("ungated", "gated", "benign"):
        mod.set_mode(variant)
        cutpoint_verdicts[variant] = _cutpoint_passes(mod, trace_dir)
        fullstub_verdicts[variant] = _fullstub_passes(mod, trace_dir)

    # Mutants are of the guarded fix, so every mutant runs in gated mode.
    mod.set_mode("gated")
    fn = _tool_def(mod)
    original = getattr(mod, fn.name)
    regions = _regions(fn)
    total = _apply(fn, -1)[1].count
    killed_cp = killed_fs = 0
    survivors: list[dict[str, str]] = []
    try:
        for k in range(total):
            mutant, mutator = _apply(fn, k)
            _install(mod, mutant)
            if _cutpoint_passes(mod, trace_dir) != cutpoint_verdicts["gated"]:
                killed_cp += 1
            else:
                survivors.append({
                    "category": _category(mutator.line, regions),
                    "mutation": mutator.description,
                })
            if _fullstub_passes(mod, trace_dir) != fullstub_verdicts["gated"]:
                killed_fs += 1
    finally:
        setattr(mod, fn.name, original)

    result = IncidentResult(
        name=name,
        model_crossings=model_crossings,
        cutpoint_verdicts=cutpoint_verdicts,
        fullstub_verdicts=fullstub_verdicts,
        mutants=total,
        killed_cutpoint=killed_cp,
        killed_fullstub=killed_fs,
        survivors=survivors,
    )
    return result, trace_dir


def _suite_ms(traces: dict[str, Path], plan_for: Callable[[ModuleType], ReplayPlan]) -> float:
    """Median wall-clock (ms) of one pass of ``plan_for`` over all incidents."""
    samples: list[float] = []
    for _ in range(SUITE_ROUNDS):
        start = perf_counter()
        for name, mod in SCENARIOS.items():
            mod.set_mode("gated")
            session = reset_session()
            session.load_trace(traces[name])
            session.enable_replay(plan_for(mod))
            mod.run_agent(user_message="stubbed")
        samples.append((perf_counter() - start) * 1000.0)
    return statistics.median(samples)


def run_all() -> tuple[list[IncidentResult], float, float]:
    results: list[IncidentResult] = []
    traces: dict[str, Path] = {}
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for name, mod in SCENARIOS.items():
            result, traces[name] = evaluate(name, mod, workdir)
            results.append(result)
        fullstub_ms = _suite_ms(traces, lambda mod: ReplayPlan())
        cutpoint_ms = _suite_ms(traces, _cutpoint_plan)
    return results, fullstub_ms, cutpoint_ms


# --- reporting --------------------------------------------------------------------- #
def _verdicts(v: dict[str, bool]) -> str:
    return "/".join("pass" if v[k] else "fail" for k in ("ungated", "gated", "benign"))


def print_report(results: list[IncidentResult], fullstub_ms: float, cutpoint_ms: float) -> None:
    print()
    print("  Verdicts on unguarded/guarded/benign code (expected: fail/pass/pass)")
    print(f"  {'Incident':<9} {'cut-point':<16} {'full-stub':<16} "
          f"{'mutants':>7} {'killed(cp)':>10} {'killed(fs)':>10}")
    print("  " + "-" * 74)
    for r in results:
        print(f"  {r.name:<9} {_verdicts(r.cutpoint_verdicts):<16} "
              f"{_verdicts(r.fullstub_verdicts):<16} {r.mutants:>7} "
              f"{r.killed_cutpoint:>10} {r.killed_fullstub:>10}")
    print("  " + "-" * 74)
    total = sum(r.mutants for r in results)
    killed_cp = sum(r.killed_cutpoint for r in results)
    killed_fs = sum(r.killed_fullstub for r in results)
    print(f"\n  mutants                : {total}")
    print(f"  killed by cut-point    : {killed_cp}/{total} ({100.0 * killed_cp / total:.1f}%)")
    print(f"  killed by full-stub    : {killed_fs}/{total}")
    print(f"  model crossings (suite): {sum(r.model_crossings for r in results)}")
    print(f"  full-stub suite pass   : {fullstub_ms:.2f} ms (median of {SUITE_ROUNDS})")
    print(f"  cut-point suite pass   : {cutpoint_ms:.2f} ms (median of {SUITE_ROUNDS})")
    counts = Counter(s["category"] for r in results for s in r.survivors)
    print("  cut-point survivors by location:")
    for key, label in _SURVIVOR_CATEGORIES.items():
        print(f"    {counts.get(key, 0):>3}  {label}")
    print("\n  Surviving mutants (cut-point):")
    for r in results:
        for s in r.survivors:
            print(f"    [{r.name}] ({s['category']}) {s['mutation']}")
    print()


def to_latex(results: list[IncidentResult], fullstub_ms: float, cutpoint_ms: float) -> str:
    n = len(results)
    total = sum(r.mutants for r in results)
    killed_cp = sum(r.killed_cutpoint for r in results)
    killed_fs = sum(r.killed_fullstub for r in results)
    fs_spec = sum(r.fullstub_verdicts["gated"] and r.fullstub_verdicts["benign"] for r in results)
    fs_detect = sum(not r.fullstub_verdicts["ungated"] for r in results)
    counts = Counter(s["category"] for r in results for s in r.survivors)
    lines = [
        "% Auto-generated by examples/benchmark/mutation.py",
        "\\newcommand{\\mutantsTotal}{%d}" % total,
        "\\newcommand{\\mutantsKilledCP}{%d}" % killed_cp,
        "\\newcommand{\\mutantsKilledFS}{%d}" % killed_fs,
        "\\newcommand{\\mutantsSurvivedCP}{%d}" % (total - killed_cp),
        "\\newcommand{\\mutationScoreCP}{%.1f}" % (100.0 * killed_cp / total),
        "\\newcommand{\\fullstubDetect}{%d/%d}" % (fs_detect, n),
        "\\newcommand{\\fullstubSpec}{%d/%d}" % (fs_spec, n),
        "\\newcommand{\\modelCrossings}{%d}" % sum(r.model_crossings for r in results),
        "\\newcommand{\\fullstubSuiteMs}{%.1f}" % fullstub_ms,
        "\\newcommand{\\cutpointSuiteMsMeasured}{%.1f}" % cutpoint_ms,
        "\\newcommand{\\survBenignBranch}{%d}" % counts.get("benign_branch", 0),
        "\\newcommand{\\survUnguardedPath}{%d}" % counts.get("unguarded_path", 0),
        "\\newcommand{\\survGuardStillBlocks}{%d}" % counts.get("guard_still_blocks", 0),
        "\\newcommand{\\survIgnoredField}{%d}" % counts.get("ignored_field", 0),
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Chronicle mutation study + full-mock baseline")
    parser.add_argument("--json", type=Path, help="write raw results as JSON")
    parser.add_argument("--tex", type=Path, help="write LaTeX macros")
    args = parser.parse_args()

    results, fullstub_ms, cutpoint_ms = run_all()
    print_report(results, fullstub_ms, cutpoint_ms)

    if args.json:
        payload = {
            "incidents": [asdict(r) for r in results],
            "fullstub_suite_ms": fullstub_ms,
            "cutpoint_suite_ms": cutpoint_ms,
        }
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"  wrote {args.json}")
    if args.tex:
        args.tex.write_text(to_latex(results, fullstub_ms, cutpoint_ms), encoding="utf-8")
        print(f"  wrote {args.tex}")


if __name__ == "__main__":
    main()
