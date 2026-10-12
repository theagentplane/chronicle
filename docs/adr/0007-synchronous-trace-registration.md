# 0007. Register the trace synchronously at the root

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-10-13 |
| Deciders | Susheem Koul, Tisha Chawla |

Backfilled from decision 4 of the [technical design](../rfcs/chronicle-technical-design.md).

## Context

Trace-level labels are written once and some consumers (TokenOps) register spans with immutable
labels before telemetry. The first Chronicle-aware service on a request path mints the
`trace_id`. Registering it can be done in the request path or lazily on first ingest.

## Options considered

### Option A: lazy registration at first ingest

- Good: no latency at the trace root.
- Bad: labels and the trace row are created implicitly.

### Option B: synchronous, idempotent registration at the trace root

- Good: simple; labels are written once up front.
- Bad: the first service on the path pays a network round trip.

## Decision

We will register the trace synchronously at the root for now. The request is idempotent (client
supplied id, write-once labels, a repeat returns the existing trace). If the control plane is
unreachable the default is fail-open (continue with the locally minted id); strict mode fails
the request. A `trace_registration: sync | lazy` setting makes a later switch cheap.

## Consequences

- **Good:** simple, and the switch to lazy needs no API change.
- **Bad or risky:** added latency at the trace root; to be measured (p50 and p99, local and
  remote control plane).
- **Follow-ups:** the latency measurement decides whether to move to `lazy` (design 12.1).

## Impact on other repositories

- control-plane: idempotent `POST /v1/traces` (design 10.2).

## Links

Design section 3.3; decision 4.
