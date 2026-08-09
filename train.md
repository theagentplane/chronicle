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

## Ideas not yet tried

- `example_coverage` is 3/4 — one `examples/` integration has no matching test file
  under `tests/`. Worth checking which one and whether it's `langgraph_demo` (needs
  the `langgraph` extra, plausibly why it's untested) before deciding whether to add
  coverage or exclude it as an intentionally-optional integration.
- `lines_before_first_code_block` is 62, 22 over the no-penalty budget of 40 — small
  score headroom, but shortening the intro risks cutting the "Why Chronicle" framing
  that likely helps conversion. Lower priority than the untested example.
