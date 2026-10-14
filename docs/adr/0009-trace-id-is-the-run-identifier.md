# 0009. Use `trace_id` as the only run identifier; there is no `run_id`

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-13 |
| Deciders | Susheem Koul |

## Context

TokenOps identifies a governed run with `run_id` and sends it in the `X-TokenOps-Run-Id` header.
Chronicle identifies a request across services with `trace_id` and propagates it in `traceparent`.
The technical design (10.3) left open whether `run_id` equals `trace_id` or is a trace label.

## Options considered

### Option A: `run_id` equals `trace_id`

- Good: one value.
- Bad: two names for one thing, and a name that still invites a second, different id later.

### Option B: `run_id` is a Trace label

- Good: TokenOps keeps its own id.
- Bad: a second identifier to keep in step, indexed and written once, for no capability.

### Option C: no `run_id`; `trace_id` is the identifier

- Good: one id, already unique, already propagated, already what replay and the control plane use.
- Bad: TokenOps must migrate off `run_id` and its headers.

## Decision

We will use `trace_id` as the only run identifier. Chronicle has no `run_id` and adds none.
Consumers key on `trace_id`. This was decided by the maintainer in the issue #67 discussion.

## Consequences

- **Good:** one id across Chronicle, the control plane and TokenOps; nothing to map.
- **Bad or risky:** TokenOps and anything that stored `run_id` must migrate.
- **Follow-ups:** TokenOps issue to drop `run_id` and `X-TokenOps-Run-Id` (design 10.3, item 2).

## Impact on other repositories

- tokenops: replace `run_id` with `trace_id` and stop sending `X-TokenOps-Run-Id`.
- control-plane: run records are keyed by `trace_id`.

## Links

Design sections 3.2 and 10.3; decision 28; issue #67.
