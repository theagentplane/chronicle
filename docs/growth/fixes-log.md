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

## Iteration 2 — untested example (2026-08-09)

- **Commit:** `dce6fcd`
- **File:** `tests/test_langgraph_demo.py` (new)
- **Broke:** nothing crashed, but `examples/langgraph_demo` was the one integration
  example with zero test coverage, so a future change could silently break it.
- **Fixed:** added a deterministic `layer1` test (`pytest.importorskip("langgraph")`
  guard) asserting both graph nodes record correctly as Envelopes.
- **Score:** 128.0 -> 133.0 (`example_coverage` 3/4 -> 4/4).
- **Status:** kept.

## Iteration 3 — CHANGELOG hygiene (2026-08-09, score-neutral)

- **Commit:** `a69627f`
- **File:** `CHANGELOG.md`
- **Fixed:** logged the iteration-1 Windows fix under `[Unreleased] / Fixed`. Not
  scored by `prepare.md`; done because a real fix with no changelog trail is a
  trust gap on its own.
- **Score:** unchanged (133.0), gates still pass.
- **Status:** kept.

## Run closed here

The scored surface saturated after iteration 2 — see `train.md` "Stopping the
score-driven part of this run here" for why the remaining gap
(`lines_before_first_code_block`) isn't worth chasing, and what that implies about
where the real growth bottleneck is (distribution, not on-page quality).
