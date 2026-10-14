# 0008. Deliver the primitives rewrite as one large pull request

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-10-13 |
| Deciders | Susheem Koul, Tisha Chawla |

## Context

The technical design (section 10.4) planned a pure-move pull request for the `src` layout first
and the removals and rewrites in separate pull requests, each under the 400-line rule. The
repository's change-size rule (`AGENTS.md`, `CONTRIBUTING.md`) asks for a split plan above about
400 lines or a stated reason. Issue #67 asks for the rewrite, the repository conventions, the
provider conformance tests and the end-to-end suite in one change.

## Options considered

### Option A: separate pull requests per component (design 10.4)

- Good: each change is small and reviewable on its own.
- Bad: the ordering was not what the maintainer chose.

### Option B: one large pull request, reviewable commit by commit

- Good: one decision point; the intermediate states never have to stay releasable.
- Bad: well above the 400-line guidance; review is harder.

## Decision

We will deliver the rewrite as one pull request, as the maintainer decided in issue #67, and keep
it reviewable by commit: tooling and conventions, pure move, primitives dependency, framework,
repository client and propagation, record and replay, provider conformance tests, end-to-end
suite, documentation. This supersedes the ordering in design section 10.4.

## Consequences

- **Good:** the clean break (decision 14) lands once.
- **Bad or risky:** reviewers must read commit by commit; the pull request description must say
  why it is one change.
- **Follow-ups:** none.

## Impact on other repositories

None.

## Links

Issue #67; design sections 10.4 and 12.3.
