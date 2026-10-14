# 0006. Keep one envelope record, mutable until closed

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-10-13 |
| Deciders | Susheem Koul, Tisha Chawla |

Backfilled from decision 5 of the [technical design](../rfcs/chronicle-technical-design.md).

## Context

A separate project needs the envelope to exist before the call completes so it can track the
input (intent capture). Sending two writes for every envelope would double the default traffic.

## Options considered

### Option A: write once at close

- Good: one write per envelope.
- Bad: nothing exists before the call completes.

### Option B: a single record, open then closed, with `emit_open` opt-in

- Good: supports intent capture without doubling default traffic.
- Bad: a crash mid-call loses the envelope (`emit_open` off) or leaves it open (`emit_open` on).

## Decision

We will keep one envelope record that is mutable until closed. The open write is sent only when
`emit_open` is on (default off); by default only the close write is sent. A closed envelope is
immutable. There is no `unfinished` state yet.

## Consequences

- **Good:** intent capture is possible; default traffic is one write per envelope.
- **Bad or risky:** the crash gap in design 2.4 is accepted for now.
- **Follow-ups:** an `unfinished` state with a timeout (design 12.1).

## Impact on other repositories

- control-plane: an envelope write supporting an open record updated at close (design 10.2).

## Links

Design sections 2.4 and 6.3; decision 5.
