# 0002. Save to the control plane only; no local stores

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-10-13 |
| Deciders | Susheem Koul, Tisha Chawla |

Backfilled from decision 8 of the [technical design](../rfcs/chronicle-technical-design.md).

## Context

Chronicle 0.5.0 could write envelopes to JSONL files, SQLite, a buffered store or a remote
control plane, and exported traces to a fixtures directory. The `Store` protocol required
`read_all` and `find_by_envelope_id`, which the remote store cannot honour (it returns empty
results that look like "no data"). The control plane already owns storage, query and
visualization (design principle P2).

## Options considered

### Option A: keep several backends behind a `Store` protocol

- Good: zero-config local quickstart; fixtures committed next to tests.
- Bad: a protocol wider than the remote backend can honour; duplicated storage and viewing
  features that the control plane owns.

### Option B: one backend, the control plane over HTTP

- Good: one place that stores; the contract is the three writes and one read replay needs.
- Bad: replay needs a reachable control plane and a trace still within retention; no local
  quickstart.

## Decision

We will have one backend: the control plane over HTTP. The JSONL and SQLite stores, `open_store`,
the buffered-store syntax, `read_all`, the local reference server and committed fixtures are
removed. Tests use an in-memory fake of the repository client kept in the test suite.

## Consequences

- **Good:** one source of truth; Chronicle stays an edge component.
- **Bad or risky:** the consequences accepted in design 5.5 (control plane required, retention
  matters, README story changes, tests and examples need rewriting). A crash can lose queued
  items because there is no local buffer on disk.
- **Follow-ups:** a local control-plane scaffold (design 12.1).

## Impact on other repositories

- control-plane: owns the read endpoint for a span's envelopes and retention (design 10.2).

## Links

Design sections 5 and 10.4; decision 8.
