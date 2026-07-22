# Contributing to Chronicle

Thanks for your interest in contributing! Chronicle is record-and-replay for
agent decision graphs, and contributions of all sizes are welcome.

## Getting started

```bash
git clone https://github.com/theagentplane/chronicle.git
cd chronicle
pip install -e ".[dev]"

python scripts/run.py demo     # interactive walkthrough
pytest -v                      # full test suite
pytest -m layer1 -v            # deterministic replay only
```

## Ground rules

- Keep pull requests small and focused on one thing.
- Every change needs tests, and CI (lint + tests) must be green before merge.
- Match the existing code style; run `ruff check .` before pushing.
- Open an issue or a GitHub Discussion before large changes so we can align.

## Developer Certificate of Origin (DCO)

This project uses the [DCO](https://developercertificate.org/) instead of a CLA.
It's a lightweight, one-line attestation that you have the right to submit your
contribution under the project's MIT license. Sign off every commit:

```bash
git commit -s -m "Your message"
```

That appends a line like `Signed-off-by: Your Name <you@example.com>` to the
commit. We recommend enabling the DCO GitHub App on the repo so it's enforced
automatically on every PR.

## Reviewer checklist (record-and-replay specifics)

Because this is a replay tool, reviewers pay special attention to:

- **Layer 1 replay must never touch the network or call the LLM.** A stray live
  call in "deterministic" replay silently invalidates every regression test.
- **Envelopes are immutable and append-only.** Don't introduce code that mutates
  a stored envelope in place.
- **No un-redacted production data in fixtures.** See `SECURITY.md` — captured
  prompts and retrieved chunks are sensitive. Scrub before committing.
- **Graph linkage stays correct** across retries and parallel invocations
  (`parent_envelope_id`, `sequence`, `invocation_index`).
- **Cut-point tests** genuinely stub upstream from the fixture and only run the
  target boundary live.
- **Envelope schema changes** ship with a version bump and a fixture migration
  path so previously committed regressions still load.

## Reporting bugs and requesting features

- Bugs: open a GitHub Issue with a minimal reproduction.
- Ideas and questions: use GitHub Discussions.
- Security issues: do **not** open a public issue — see `SECURITY.md`.
