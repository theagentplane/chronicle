# Growth strategy log (edited every iteration)

Current focus, what's been tried, and why. See `program.md` for the rules and
`prepare.md` for how `score` is computed. Per-iteration structured log lives in
`results.tsv`.

## Current focus

Iteration 1 surfaced a real onboarding blocker (below) before any deliberate
"growth" idea was even tried — fixing it first, then moving to the planned levers:
the untested example (`example_coverage: 3/4`), and the outreach package
(`docs/growth/target-list.md` + `docs/growth/outreach-templates.md`), which is a
one-time deliverable rather than something the score tracks.

## Log

### Baseline (commit `c94b5e3`, `main` HEAD at branch time)
- Ran `scripts/growth_eval.py --json` as-is, no changes.
- **Result: score 0.0 — TTFSR gate failed.** The exact command the README's Demos
  table tells a new user to run, `python examples/financial_incidents/run.py refund
  test`, crashes on a fresh Windows install: `UnicodeEncodeError` from the console's
  default `cp1252` codepage choking on a box-drawing character (`─`, U+2500) the demo
  prints. Nobody had caught this because dev environments here already have UTF-8
  configured; a first-time Windows user hitting this from a cold clone would not.
- This wasn't a planned experiment — it's the eval's first real find, exactly the
  point of a TTFSR-style gate: it catches what a README read-through can't.

### Iteration 1 (keep): force UTF-8 stdout/stderr in the demo entry point
- **Change:** `examples/financial_incidents/run.py` now reconfigures `sys.stdout` /
  `sys.stderr` to UTF-8 (`errors="replace"`) at import time if the console isn't
  already UTF-8, before any output is printed.
- **Why here and not elsewhere:** checked every script the README actually tells a
  user to run (`examples/deletion_agent/record_incident.py`, `show_trace.py`,
  `run_cutpoint_demo.py`) — their runtime `print()` output is pure ASCII, so they
  don't have this failure mode. Only `financial_incidents/run.py`'s `_line()` helper
  prints a non-ASCII character. Fixing only the file that's actually broken, not
  pre-emptively wrapping files that can't hit this.
- **Result: score 0.0 -> 128.0.** TTFSR now passes (43.8s fresh venv install + demo
  run), `tests_green` stays true, all other components unchanged (0 broken links,
  version consistent, 7/7 doc checklist, 3/4 example coverage, 62 lines before first
  code block).
- **Kept.**

### Iteration 2 (keep): test coverage for `examples/langgraph_demo`
- **Confirmed the gap:** `langgraph_demo` was the one example with no matching file
  under `tests/` (checked which by grepping test files for each example dir name).
  It's fully deterministic (canned node outputs, no live model call), just never had
  a test written.
- **Change:** `tests/test_langgraph_demo.py`, `@pytest.mark.layer1`, guarded with
  `pytest.importorskip("langgraph")` so it skips cleanly for anyone who didn't
  install the `langgraph` extra rather than failing.
- **Result: score 128.0 -> 133.0** (`example_coverage` 3/4 -> 4/4). All other
  components unchanged.
- **Kept.**

### Iteration 3 (keep, score-neutral): CHANGELOG entry for the iteration 1 fix
- **Change:** added a `### Fixed` entry to `CHANGELOG.md`'s `[Unreleased]` section for
  the Windows encoding fix. Not driven by the score (`prepare.md`'s formula doesn't
  read CHANGELOG prose) — a real fix with no changelog trail is its own small honesty
  gap for anyone diffing releases.
- **Result: score unchanged at 133.0**, all gates still pass.
- **Kept.**

## Stopping the score-driven part of this run here

After iteration 2, every scored component in `prepare.md` is at its ceiling except
`lines_before_first_code_block` (62 lines, 22 over the no-penalty budget of 40 -> an
11-point deduction). I looked at what's actually in those 62 lines: badges, the demo
GIF, a one-paragraph problem statement, a collapsed `<details>` glossary, and the
"Why Chronicle" bullet list. That's real, load-bearing content for a first-time
visitor, not padding — cutting it to chase 11 points would be optimizing the proxy
at the product's expense, which `program.md` explicitly rules out (and which the
metric itself can't catch, since it counts raw markdown lines and can't tell a
`<details>` block that's collapsed by default from visible prose).

That's a real limitation of this specific score, worth naming rather than working
around: it doesn't discount collapsed sections. Not fixing it retroactively here
since the two iterations that mattered (the crash, the coverage gap) are done and a
metric-definition change mid-run should be a deliberate human call, not something
slipped in to justify more iterations.

**Net result of this run: two real bugs fixed** (a cross-platform crash in the
exact command the README tells people to run, and an untested example), **not
five manufactured diffs.** The actual growth bottleneck, per the baseline traffic
numbers in `docs/growth/stars.tsv` (44 unique visitors / 14 days against 10 lifetime
stars), is discovery, not on-page conversion — which is what
`docs/growth/target-list.md` and `outreach-templates.md` are for.
