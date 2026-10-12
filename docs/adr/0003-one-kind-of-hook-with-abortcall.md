# 0003. Use one kind of hook, with `AbortCall` always propagating

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-10-13 |
| Deciders | Susheem Koul, Tisha Chawla |

Backfilled from decision 6 of the [technical design](../rfcs/chronicle-technical-design.md).

## Context

In 0.5.0 the session had four single-slot callbacks (`on_enter`, `on_crossing`, `on_leave`,
`on_record`) with no ordering, and an exception from a post-call callback propagated after the
function had already run. Integrations such as TokenOps patched `reset_session` to re-attach
callbacks. A governor must be able to stop a call on purpose.

## Options considered

### Option A: keep single-slot callbacks

- Good: no change.
- Bad: no ordering; one integration overwrites another; failures after the call break the caller.

### Option B: one kind of hook with four events, a global fail-call flag and `AbortCall`

- Good: simple contract; a governor can still stop a call; hooks are registered on a session or
  as defaults.
- Bad: what hooks may see and do is not reviewed yet (future scope).

## Decision

We will have one kind of hook with the events `enter`, `leave`, `crossing` and `record`, run in
registration order. `hooks.fail_call_on_error` (default false) decides whether a hook failure
fails the call. `AbortCall` always propagates, regardless of the flag, because without it
swallowing failures would silently disable governance.

## Consequences

- **Good:** a governor has a deliberate way to halt a call; no more patching `reset_session`.
- **Bad or risky:** with the flag true, an exception from `crossing`, `record` or `leave` fails
  the call even though the function completed. Hook security is future scope.
- **Follow-ups:** hook security review (design 12.1); the `enabled = false` versus hooks
  question (decided in the CHANGELOG).

## Impact on other repositories

- tokenops: raise `AbortCall` to halt a call and register as a default hook (design 10.3).

## Links

Design section 4.4; decision 6.
