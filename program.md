# Chronicle growth research

Modeled on [karpathy/autoresearch](https://github.com/karpathy/autoresearch): instead of
optimizing `val_bpb` on a training loop, this loop optimizes an **adoption-readiness
score** for the Chronicle repo, with real GitHub stars tracked as the slow, noisy,
ground-truth outcome it exists to move.

## Goal

**100 GitHub stars** on [theagentplane/chronicle](https://github.com/theagentplane/chronicle) (`main`).
Baseline at the start of this run (2026-08-09): 10 stars, 2 forks, 1 watcher, 712 PyPI
downloads/month, 44 unique repo visitors over the prior 14 days.

Stars move on a timescale of days to weeks and are confounded by external noise (a
single HN front-page hit can dwarf months of organic growth), so they cannot be the
per-iteration signal a fast loop needs. See `prepare.md` for how the loop's actual
per-iteration metric is defined, and `docs/growth/stars.tsv` for the real, slow
ground-truth series.

## Setup

1. Work happens on a dedicated branch off `main`: `growth/<tag>` (e.g. `growth/aug9`).
   `dev` is a stale branch, 19 commits behind `main` — never branch from it.
2. Read `prepare.md` (fixed, defines the eval) and `train.md` (the file you edit each
   iteration: current strategy, hypotheses, running log).
3. `scripts/growth_eval.py` is the eval harness. Run it with `--skip-ttfsr` while
   drafting (fast, static checks only); run it without that flag before deciding
   keep/discard (adds the real fresh-venv install + demo check, ~40-60s).

## What you CAN do

- Edit `README.md`, `docs/`, `examples/`, and packaging metadata (`pyproject.toml`
  description/classifiers, `CHANGELOG.md`).
- Add small, additive, non-breaking DX/CLI affordances (e.g. a friendlier error
  message, a new `examples/` integration, a `--help` improvement) as long as the
  existing test suite stays green and nothing in `chronicle/`'s public behavior
  changes for existing callers.
- Draft outreach content (emails, forum/Discord posts, social copy) into
  `docs/growth/outreach-templates.md` and `docs/growth/target-list.md`.

## What you CANNOT do

- Modify `chronicle/` core library behavior beyond additive, backward-compatible DX.
  A growth loop must never regress the actual product.
- Modify `prepare.md` or `scripts/growth_eval.py` to make the metric easier to hit.
  If the metric itself seems wrong, say so in `train.md` and flag it to a human —
  don't quietly loosen your own eval.
- Fabricate stats, benchmarks, testimonials, or comparisons. Every claim in README/docs
  must trace to something real and checkable.
- Buy, farm, trade, or bot stars/forks/downloads, or ask for stars without offering
  something real in return.
- Send any email, DM, or social/forum post yourself, or treat a past approval as
  covering a future send. Outreach content gets drafted here and reviewed by Tisha
  before anything goes out — each batch, explicitly.
- No em dashes or en dashes anywhere (standing repo-wide style rule).

## The loop

LOOP for the agreed number of iterations:

1. Read `train.md` for the current strategy and what's already been tried.
2. Pick one concrete lever (a specific README section, a broken link, an example
   without test coverage, a doc gap) and make the change.
3. `git commit` the change.
4. `python scripts/growth_eval.py --json` (full run, TTFSR included).
5. Append a row to `results.tsv` (commit hash, score, ttfsr_pass, tests_green, status,
   description).
6. If `score` improved and both `ttfsr_pass` and `tests_green` are true: **keep** —
   advance the branch, update `train.md` with what worked and why.
7. Otherwise: **discard** — `git reset` back to the prior commit, note in `train.md`
   why it didn't pan out so the next iteration doesn't repeat it.

**Simplicity criterion** (same spirit as autoresearch): a change that raises the score
by adding awkward complexity is not automatically worth keeping — weigh it against
`train.md`'s running notes. A score-neutral change that measurably simplifies the
first-run path is a good outcome too.

**Stopping point for this run:** a fixed, small batch of iterations (agreed with Tisha
per-run, not open-ended) — review the branch together before merging anything to
`main` or sending any outreach.
