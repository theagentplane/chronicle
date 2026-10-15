# Architecture Decision Records

An ADR is a short note that records **one decision**: what we chose, why, what else we
considered, and what it costs us. We keep them in the repository so the reasoning stays next to
the code and survives people changing teams.

## When to write one

Write an ADR when a decision:

- changes how the system is structured (modules, layers, who owns what),
- changes a public interface, a data format or a schema,
- adds, removes or replaces a significant dependency or tool,
- is hard or expensive to reverse, or
- affects another repository (chronicle, primitives, control-plane, tokenops).

Do not write one for routine changes: a bug fix, a rename, a small refactor.

## How to write one

1. Pick the next number: look at the files in this folder and add one to the highest.
2. Copy [template.md](template.md) to `NNNN-short-kebab-title.md`.
3. Fill it in. Keep it to about one page.
4. Open a pull request. Start with status **Proposed**; set **Accepted** when the people
   named as deciders agree.
5. Add a row to the index below.

## Rules

- **An accepted ADR is not rewritten.** Fixing a typo is fine. To change a decision, write a new
  ADR that says it supersedes the old one, and update only the old ADR's status line and link.
- **One decision per ADR.**
- **Say what we gave up.** Every real decision has a cost; if the Consequences section lists
  only good things, it is not finished.
- **Decisions that span repositories** are recorded in the repository that owns the decision. The
  "Impact on other repositories" section says what must change elsewhere, and the other
  repositories link to the ADR.

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-remote-only-repositories.md) | Save to the control plane only; no local stores | Proposed |
| [0003](0003-one-kind-of-hook-with-abortcall.md) | Use one kind of hook, with `AbortCall` always propagating | Proposed |
| [0004](0004-propagation-allow-list-default-deny.md) | Inject `traceparent` only to allow-listed hosts (default deny) | Proposed |
| [0005](0005-raw-always-stored.md) | Store the raw input and output of every boundary | Proposed |
| [0006](0006-single-mutable-envelope-record.md) | Keep one envelope record, mutable until closed | Proposed |
| [0007](0007-synchronous-trace-registration.md) | Register the trace synchronously at the root | Proposed |
| [0008](0008-rewrite-delivered-as-one-change.md) | Deliver the primitives rewrite as one large pull request | Proposed |
| [0009](0009-trace-id-is-the-run-identifier.md) | Use `trace_id` as the only run identifier; there is no `run_id` | Accepted |
| [0010](0010-public-current-session-accessor.md) | Expose the active session as `chronicle.current_session()` | Proposed |

Related repositories: [chronicle](https://github.com/theagentplane/chronicle), [primitives](https://github.com/theagentplane/primitives),
[control-plane](https://github.com/theagentplane/control-plane), [tokenops](https://github.com/theagentplane/tokenops).
