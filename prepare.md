# Growth eval (fixed — do not modify as part of a growth iteration)

This defines the loop's per-iteration metric: the **adoption-readiness score**. It is
implemented in `scripts/growth_eval.py`, which is the ground truth — this file
documents what that script does and why, so the formula is auditable in one place.

Every check below is a file-system read, a subprocess exit code, or a count. None of
it is an LLM self-grade, so the score can't be improved by writing more persuasive
prose about the repo — only by actually fixing something.

## Gates (hard pass/fail — a failing gate forces score = 0)

- **TTFSR** ("time to first successful run"): build a brand-new venv, `pip install -e .`
  from a clean checkout, then run the exact no-API-key command the README's Demos
  table advertises (`python examples/financial_incidents/run.py refund test`).
  This is the same idea as autoresearch treating a crash as an automatic discard —
  if the thing the README tells a new user to run doesn't run, nothing else about the
  repo's polish matters.
- **tests_green**: `pytest -m layer1` (deterministic, no LLM calls) must pass. A growth
  edit that breaks the existing suite is never a "keep," regardless of score.

## Scored components (only computed if both gates pass)

Starting from 100:

| Component | Effect | Why |
|---|---|---|
| `broken_links` (count) | `-10` each | Internal markdown links (README + docs) that point at a file that doesn't exist. External `http(s)` links are excluded from the automated check — they're too flaky/network-dependent to gate a deterministic score on. |
| `lines_before_first_code_block` | `-0.5` per line over 40 | Proxy for "how long before a visitor sees working code." Penalizes creeping intro copy; doesn't reward deleting the intro entirely (there's no floor bonus below 40). |
| `example_coverage` (examples/ dirs with a matching test file) | `+5` each | An example nobody tests is an example that quietly rots and breaks on the next release. |
| `version_consistency` (pyproject == `__init__.__version__` == latest CHANGELOG entry) | `+10` if consistent | A README PyPI badge that doesn't match reality is the fastest way to lose a new visitor's trust. |
| `doc_checklist` (required README sections present: Install, Quick start, Why Chronicle, How Chronicle compares, FAQ, Roadmap, Demos) | `+2` each | Structural completeness, checked by heading presence — not by judging whether the prose is good. |

**Score = 100 − 10×broken_links − 0.5×max(0, lines_before_first_code_block − 40)
+ 5×example_coverage + 10×version_consistency + 2×doc_checklist_present**

## Running it

```bash
python scripts/growth_eval.py --skip-ttfsr   # fast, static checks only — use while drafting
python scripts/growth_eval.py --json          # full run incl. TTFSR — use before keep/discard
```

## Ground truth (not part of the per-iteration score)

Real stars, forks, traffic, and PyPI downloads are pulled by `scripts/growth_snapshot.py`
into `docs/growth/stars.tsv`. Check weekly, not per-iteration — the point is to confirm
the proxy score is actually correlated with real growth over time, not to chase it
directly (it moves too slowly and noisily for that).
