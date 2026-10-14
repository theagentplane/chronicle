# 0004. Inject `traceparent` only to allow-listed hosts (default deny)

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-10-13 |
| Deciders | Susheem Koul, Tisha Chawla |

Backfilled from decision 7 of the [technical design](../rfcs/chronicle-technical-design.md).

## Context

Chronicle propagates the trace to downstream services in the W3C `traceparent` header, injected
by an `httpx` instrumenter. LLM SDKs use `httpx` internally, so without a filter the header
would also be sent to third parties such as `api.openai.com`, leaking trace ids and
double-recording the call.

## Options considered

### Option A: inject on every `httpx` request

- Good: nothing to configure.
- Bad: leaks trace ids to third parties; the LLM call is recorded twice.

### Option B: inject only to configured hosts; default deny

- Good: nothing leaves unless the developer listed the peer.
- Bad: propagation does nothing until `inject_hosts` is configured.

## Decision

We will inject only to hosts in the `inject_hosts` allow-list. The default is deny.

## Consequences

- **Good:** no trace id reaches a provider host by accident.
- **Bad or risky:** a forgotten allow-list entry silently breaks the cross-service link.
- **Follow-ups:** trust of an inbound `traceparent` is future scope (design 12.1).

## Impact on other repositories

None.

## Links

Design section 8.3; decision 7.
