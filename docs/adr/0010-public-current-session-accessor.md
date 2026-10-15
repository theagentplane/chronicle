# 0010. Expose the active session as `chronicle.current_session()`

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-10-15 |
| Deciders | Susheem Koul |

## Context

`chronicle.span` and `chronicle.record` open a span, but there was no public way to read the active
one. TokenOps (issue 162) treats its run as a Chronicle trace and must know the active span's
`trace_id`, `span_id` and `parent_envelope_id` before it opens a call. It currently imports
`chronicle.framework.context.session_context_utils.current_session`, a private module path with no
stability promise. This adds a name to the public API, so it falls under "changes a public
interface" in the ADR criteria.

## Options considered

### Option A: keep importing the private framework path

- Good: no change in Chronicle.
- Bad: consumers break on any internal move; the framework layer is not a contract.

### Option B: export `current_session` from `chronicle`

- Good: a stable, documented name; read-only; reuses the framework function unchanged.
- Bad: `RecordingSession` (already public) becomes something callers hold and read.

### Option C: a narrower accessor returning only the ids

- Good: exposes less.
- Bad: a new type to maintain; callers needing `service` or `metadata` would ask again.

## Decision

We will export `current_session()` from `chronicle.interfaces` and `chronicle` (option B). It
returns the explicit span's session or `None`, and never creates one. The ambient session used by
boundaries called outside a span is deliberately not returned.

## Consequences

- **Good:** TokenOps and other integrations stop depending on a private module.
- **Bad or risky:** `RecordingSession`'s attributes `trace_id`, `span_id` and `parent_envelope_id`
  become relied upon and fall under SemVer.
- **Follow-ups:** none.

## Impact on other repositories

- tokenops: replace the private import in `control/chronicle_trace_utils.py` (PR 167) with
  `from chronicle import current_session`.

## Links

ADR 0009; CHANGELOG `[Unreleased]`; TokenOps issue 162.
