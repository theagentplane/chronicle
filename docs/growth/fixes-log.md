# Growth-loop fixes log

One entry per loop iteration that changed something (skipped/discarded attempts are
in `results.tsv` and narrated in `train.md`, not repeated here). This file is the
flat, chronological "what actually shipped" list; `train.md` has the reasoning.

---

## Iteration 1 — Windows demo crash (2026-08-09)

- **Commit:** `9775deb`
- **File:** `examples/financial_incidents/run.py`
- **Broke:** the exact command the README's Demos table tells a new user to run,
  `python examples/financial_incidents/run.py refund test`, crashed on a fresh
  Windows install with `UnicodeEncodeError` — the console's default `cp1252`
  codepage can't encode the box-drawing character (`─`, U+2500) the demo prints.
- **Fixed:** reconfigure `sys.stdout`/`sys.stderr` to UTF-8 (`errors="replace"`) at
  the top of the script if the console isn't already UTF-8, before any output prints.
- **Score:** 0.0 -> 128.0 (`scripts/growth_eval.py`; TTFSR gate was the failure).
- **Status:** kept.
