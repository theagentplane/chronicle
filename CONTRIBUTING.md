# Contributing to Chronicle

Thanks for your interest in contributing! Chronicle is the edge SDK of the AgentPlane suite: it
records what an agent did, saves it to the control plane and replays a request. Contributions of all
sizes are welcome. Two other products depend on its behaviour (the control plane and TokenOps), so
changes are reviewed with that in mind.

## Setup

Uses [uv](https://docs.astral.sh/uv/) and Python 3.10 to 3.13.

```bash
git clone https://github.com/theagentplane/chronicle.git
cd chronicle
uv sync                      # creates the environment with the dev group
uv run pre-commit install    # optional: run the checks on every commit
```

## Checks (CI runs the same ones)

```bash
uv run ruff check .
uv run ruff format --check .
uv run python -m mypy                       # --strict, on src and tests
uv run python -m pytest --cov -m "not e2e and not live"
uv run python -m pytest -m e2e tests/e2e    # multi-agent systems, localhost only
uv build && uv run twine check dist/*
```

On Windows use `python -m pytest`; it is the reliable invocation. Everything must also work on Linux.

## Ground rules

- **Read the design and the ADRs first.** [`docs/rfcs/chronicle-technical-design.md`](docs/rfcs/chronicle-technical-design.md)
  is the spec and [`docs/adr/`](docs/adr/README.md) records the decisions. If the code and the design
  disagree, raise it before changing either. Never rewrite an accepted ADR; supersede it.
- **Do not copy the entities.** `Trace`, `Span`, `Envelope`, ids, enums and `TraceContext` are
  imported from `agentplane-primitives`. A gap there is an issue in that repository.
- **Respect the layers** (design 1.1): framework has no network; only `repositories` does I/O;
  capabilities build on both; interfaces are what the developer touches. Each layer imports only
  from the ones before it.
- **One concept per file.** Each module has a docstring saying what it is and which design section it
  comes from. Models and functions live apart (`*_types.py`, `*_utils.py`). `__init__.py`
  re-exports with `__all__`.
- **Python 3.10 syntax.** No `typing.Self`, no `except*`, no `tomllib` at import time.
- **Every change needs tests**, and a CHANGELOG entry classified as compatible or breaking.
- **Tests never touch the network** beyond localhost. Live-provider tests are opt-in (`tests/live`).

## Change size

Small changes are easier to review, easier to revert and safer for the products that depend on this
package.

- **Estimate before you start.** Count lines added plus removed. Do not count generated files,
  lockfiles, golden test data (`tests/providers/**.json`) or pure moves and renames.
- **Above about 400 lines, plan first.** Write a short plan: logical components, each reviewable on
  its own, passing CI, ordered so each builds on the one before. Put it in the issue or pull request
  description and open one pull request per component.
- **Split by logical component, not by size.**
- **An exception needs a stated reason** in the pull request description: boilerplate, a mechanical
  change, generated code, or a maintainer decision to deliver one change (as for the primitives
  rewrite, ADR 0008). Even then, keep the history reviewable commit by commit.

A workflow (`.github/workflows/pr-size.yml`) enforces nothing: over 400 lines it adds the
`size/large` label and one comment. It never fails and is not a required check.

## Developer Certificate of Origin (DCO)

This project uses the [DCO](https://developercertificate.org/) instead of a CLA. Sign off every commit:

```bash
git commit -s -m "Add the Span writer"
```

## Commits and pull requests

- Write commit messages in the imperative mood ("Add the Span writer").
- Pull request descriptions have a summary, a compatibility section and the checklist from the
  template. Link the issue.
- CI must be green and CODEOWNERS review is required to merge.

## Reviewer checklist

Because this is a record-and-replay tool that sits inside other people's processes, reviewers pay
special attention to:

- **Transparency (P3).** The wrapped function's return value and exceptions are never changed, except
  by a deliberate `AbortCall`. Recording errors are caught and never reach the caller.
- **No raw secrets leave the process.** Redaction runs on the JSON form before anything is sent, and
  canonical fields are derived from the redacted raw. New fields that carry user data are covered.
- **Injection only to allow-listed hosts.** `traceparent` is never sent to a host that is not in
  `inject_hosts`; default deny holds.
- **Primitives models are imported, not copied.** No local `Trace`, `Span` or `Envelope`, and no
  hand-written parser for payloads the models can validate.
- **Replay never writes** to the control plane, never calls the LLM for a STUB, and advances the
  cursor even when a RUN boundary raises.
- **Counters stay span-local** and correct under threads and async tasks (`sequence`,
  `invocation_index`, the envelope stack).
- **Layering holds**: no network in the framework layer.
- **Wire changes** keep the contract test (`tests/test_wire_contract.py`) green or update it with the
  control plane.
- **Recording is fail-open** unless strict delivery is configured.

## Reporting bugs and requesting features

- Bugs: open a GitHub issue with a minimal reproduction.
- API or schema changes: use the *API or schema change proposal* template before writing code.
- Ideas and questions: use GitHub Discussions.
- Security issues: do **not** open a public issue; see `SECURITY.md`.
