# Agent instructions

Chronicle is the edge SDK of the AgentPlane suite: it runs inside an agent's own process and
**records** what the agent did at each decision point, **saves** it to the control plane over
HTTP, and **replays** a recorded request so a fix can be tested without live LLM calls. It stores
nothing locally and has no UI.

This file is read by AI coding agents (Claude Code, Codex, Cursor, Copilot and others). Humans
may find it useful too.

## Source of truth

- The design is [`docs/rfcs/chronicle-technical-design.md`](docs/rfcs/chronicle-technical-design.md).
  If the code and the design disagree, stop and ask; do not pick one silently.
- The entities (`Trace`, `Span`, `Envelope`, ids, enums, `TraceContext`) come from
  [`agentplane-primitives`](https://github.com/theagentplane/primitives) (pinned `==0.1.*`).
  **Never define a local copy of an entity** (design principle P5). A gap in primitives is an
  issue in the primitives repository, not a workaround here.
- The HTTP request and response wrappers belong to the control plane (primitives ADR 0003);
  Chronicle reads the write result and error body itself and has a contract test for them.

## Architecture decisions

Decisions that shape this repository are recorded as ADRs in [`docs/adr/`](docs/adr/README.md).

- **Before changing architecture,** read the ADRs: structure, public interfaces, data formats,
  dependencies or anything shared with another repository. Do not undo an accepted decision
  silently. If a change conflicts with one, say so and propose a new ADR that supersedes it.
- **When asked to record a decision,** or when you make one that meets the criteria in
  `docs/adr/README.md`, write an ADR: copy `docs/adr/template.md`, use the next free number,
  keep it to about a page, and add it to the index.
- **Do not invent reasoning.** If you do not know why something was decided or which alternatives
  were weighed, ask. Leave the status as *Proposed*: the people named as deciders accept it.
- **Never rewrite an accepted ADR.** Supersede it with a new one.

## Layers (design 1.1)

Each layer imports only from the ones above it.

| Layer | Package | Rule |
|---|---|---|
| Primitives | `agentplane_primitives` (external) | Data only. |
| Framework | `chronicle.framework` | In-process machinery. **No network.** |
| Repositories | `chronicle.repositories` | The **only** place that does I/O. |
| Capabilities | `chronicle.capabilities` | Record and replay workflows. |
| Interfaces | `chronicle.interfaces`, `chronicle.__init__` | What the developer touches. |

## Code layout and style

- `src` layout, typed package (`py.typed`), Python 3.10 to 3.13 (no syntax newer than 3.10).
- One concept per file, with a module docstring that says what it is and which design section it
  comes from. Folders are named for what they hold; helper modules are suffixed for what they
  are (`*_utils.py`, `*_types.py`). `__init__.py` re-exports the public names with `__all__`.
- Types and models, and functions, live apart: no functions in model modules, no models in utils.
- Must work on Windows and Linux. On Windows use `python -m pytest`.
- Tooling: `uv`, `ruff` (line length 100), `mypy --strict`, `pytest`. Run the checks listed in
  [CONTRIBUTING.md](CONTRIBUTING.md) before you finish.

## Invariants (do not break)

- **Transparency (P3):** the caller always gets the real return value or the real exception,
  except for an `AbortCall` raised deliberately by a hook.
- **No raw secrets leave the process:** redaction runs on the JSON form before anything is sent.
- **Injection only to allow-listed hosts:** the `traceparent` header is never sent to a host that
  is not configured (default deny).
- **Recording never breaks the agent** unless strict delivery is configured.

## Change size

- **Estimate before writing code:** lines added plus removed, not counting generated files,
  lockfiles, golden test data or pure moves and renames.
- **If the estimate is above 400 lines, stop and plan.** Propose to the user a short plan that
  splits the work into logical components (each reviewable on its own, passing CI, in order), and
  wait for agreement before implementing. Open one pull request per component.
- **Keep one change as one thing.** Do not mix unrelated changes into a pull request.
- Staying above 400 lines is acceptable for boilerplate, mechanical changes or generated code,
  or when the maintainer has decided on one change (as for the primitives rewrite), but say why
  in the pull request description and keep the work reviewable commit by commit.

## Related repositories

[chronicle](https://github.com/theagentplane/chronicle) (edge SDK: record, save, replay) ·
[primitives](https://github.com/theagentplane/primitives) (shared schemas) ·
[control-plane](https://github.com/theagentplane/control-plane) (storage, query, UI) ·
[tokenops](https://github.com/theagentplane/tokenops) (cost governance)
