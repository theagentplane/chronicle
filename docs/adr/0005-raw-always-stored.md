# 0005. Store the raw input and output of every boundary

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-10-13 |
| Deciders | Susheem Koul, Tisha Chawla |

Backfilled from decision 20 of the [technical design](../rfcs/chronicle-technical-design.md).

## Context

In 0.5.0 replay rebuilt a return value from the canonical fields with a fixed per-kind reverse
mapping. That lost data: an SDK-object return was stored as its `repr`, extra keys of a dict
return were dropped, and input arguments were echoed into the stub return.

## Options considered

### Option A: store canonical fields only and map back on replay

- Good: smaller payloads.
- Bad: lossy; needs a reverse mapping per provider.

### Option B: store the raw input and output as well as the canonical fields

- Good: replay hands back `output.raw` and needs no reverse mapping; canonical fields can be
  re-derived if an adapter is fixed.
- Bad: for `llm` envelopes the payload is roughly double.

## Decision

We will always store `input.raw` and `output.raw`, in JSON form, for every kind. Canonical
fields are derived from raw and used for cost, display and queries. Adapters are one-way
(`to_canonical`); there is no `from_canonical`.

## Consequences

- **Good:** lossless replay for JSON outputs; no reverse mapping.
- **Bad or risky:** roughly doubled `llm` payloads; raw must be redacted too; non-JSON values
  are stored as their `repr` and cannot be restored (serialization hardening is future scope).
- **Follow-ups:** rebuilding Python types on replay (design 12.1).

## Impact on other repositories

- control-plane: payload size and storage cost.

## Links

Design sections 2.3 and 7.3; decisions 10 and 20.
