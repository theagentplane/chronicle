# RFC: Control plane HTTP API (fast, authenticated, durable)

| Field | Value |
|---|---|
| Status | Draft |
| Author | Chronicle / AgentPlane |
| Created | 2026-08-13 |
| Related | [#30](https://github.com/theagentplane/chronicle/issues/30) (shared plane), [#40](https://github.com/theagentplane/chronicle/issues/40) (attribution / dims), [#41](https://github.com/theagentplane/chronicle/pull/41) (dims + nest parents shipped) |
| Supersedes | Softens the reference server in `examples/control_plane/` toward a production contract |

## Summary

Define the **agent-facing and dashboard-facing HTTP API** for the shared Chronicle
control plane. Agents append envelopes over HTTPS; the plane authenticates callers,
acknowledges only after durable persistence (or durable queue handoff), and serves
indexed reads for the shared dashboard / TokenOps.

**Design pillars:** fast · authenticated · durable.

```
Agents (RemoteStore / buffered)
        │  HTTPS + auth
        ▼
   Ingest API  ──ack──► durable write or durable queue
        │
        ▼
   Postgres (or equiv.) + indexes on trace_id / attributes
        │
        ▼
   Query API  ◄── dashboard / TokenOps / shared viz
```

## Motivation

Today Chronicle can persist to:

- local **JSONL** / **SQLite** (single host),
- **RemoteStore** → `POST /envelopes` on a reference HTTP server (`examples/control_plane`).

The reference server is unauthenticated, SQLite-backed, and sync-acks after a local
append. That is fine for demos; it is not production. Multi-agent deployments need:

1. One place many agents write.
2. Auth so only trusted agents/services ingest and read.
3. Durability guarantees the agent can trust (or explicitly accept “best effort”).
4. Fast ingest under burst (batching, backpressure).
5. Query by `trace_id` and **attributes** (`session_id`, `message_id`, …)
   for the dashboard — not ad-hoc JSONL scans inside the library.

This RFC locks the **HTTP API + durability/auth semantics**. Implementation can live
in a dedicated control-plane service (see #30); Chronicle keeps emitting envelopes
and attributes.

## Goals

- **Fast** — low agent-side latency; batch ingest; optional async ack modes.
- **Authenticated** — mutual trust for ingest and for privileged reads.
- **Durable** — acknowledged writes survive process crash (DB fsync or durable queue).
- Stable JSON envelope body compatible with today’s `Envelope` schema (+ `attributes`,
  `start_time`, nest parents).
- Clear separation: **ingest** (agents) vs **query** (dashboard / TokenOps).
- Fail-open option on the agent (`RemoteStore` today drops on error) vs strict mode
  for pipelines that must not lose data.

## Non-goals

- Replacing Chronicle’s local JSONL/SQLite for unit tests and fixtures.
- Building the full dashboard UI in this RFC (shared viz is a separate track).
- Making gRPC/OTLP the primary agent ingest (OTLP remains an optional *export*).
- Direct agent→Postgres (credentials and coupling).
- Defining TokenOps ledger schema (plane may co-host; ledger is TokenOps-owned).

## Design pillars

### Fast

| Mechanism | Detail |
|---|---|
| **Batch ingest** | `POST /v1/envelopes:batch` accepts `N` envelopes in one RTT (primary hot path; matches `BufferedStore`). |
| **Single ingest** | `POST /v1/envelopes` kept for simplicity / low volume. |
| **Bounded bodies** | Max request size (e.g. 1–4 MiB); reject oversize with `413`. |
| **Cheap auth** | Bearer API key or mTLS verified at edge; no per-envelope round-trips to IdP on the hot path (cache JWKS / static keys). |
| **Ack modes** | `Durability: sync` (default for strict) vs `Durability: queued` (ack after durable queue persistence — lower latency under load). |
| **Compression** | Optional `Content-Encoding: gzip` on ingest. |
| **Agent buffering** | Continue recommending `buffered:N:https://…` so the agent coalesces crossings. |

Target (aspirational, to validate in load tests): p99 single-envelope ingest ack
&lt; 50ms within a region on `queued` mode; sync mode dominated by DB commit.

### Authenticated

| Concern | Proposal |
|---|---|
| **Transport** | HTTPS only in production (TLS 1.2+). |
| **Agent ingest** | `Authorization: Bearer <agent_api_key>` (scoped: `ingest`). Keys are per-environment / per-service, rotatable. |
| **Dashboard / TokenOps read** | Separate keys or JWT with scopes `read`, `admin`. |
| **Optional mTLS** | Service mesh / private CA for agent fleets that prefer certs over long-lived bearers. |
| **Tenancy** | Every key maps to a `tenant_id` (or `project_id`). All writes/reads are tenant-scoped. Envelope attributes must not be able to escape the tenant. |
| **Rejection** | `401` missing/invalid creds; `403` valid creds, wrong scope. |

Reference `RemoteStore` already supports `api_key` → `Authorization: Bearer …`. The
plane must enforce it; today’s example server does not.

### Durable

**Definition of “acknowledged”:**

1. **`Durability: sync` (default for privileged pipelines)**  
   Handler returns `2xx` only after the envelope row(s) are committed to the primary
   store (Postgres `COMMIT`, or equivalent). Client may treat `2xx` as “will not be
   lost if the ingest process dies.”

2. **`Durability: queued`**  
   Handler returns `2xx` only after the payload is persisted to a **durable queue**
   (SQS, Pub/Sub, Kafka with acked produce, etc.). A worker then writes to Postgres.
   Lower latency / better burst absorption; brief delay before query visibility.

3. **Never** ack solely from an in-memory buffer.

**Idempotency:**

- Clients may send `Idempotency-Key: <uuid>` (or use `(trace_id, envelope_id)` as the natural key).
- `trace_id` is an OTel trace id (32 lowercase hex chars) and `envelope_id` an OTel span id
  (16 lowercase hex chars). A span id is only 8 bytes, so it is unique **within a trace**,
  never across a tenant: always key on the pair.
- Re-POST of the same `(trace_id, envelope_id)` within a tenant is a no-op success (`200` with
  `deduped: true`), not a duplicate row.
- Enables safe retries after timeouts.

**Retention:** configurable per tenant (e.g. 30/90 days); hot store + optional cold
object storage later. Out of scope for v1 API shapes beyond a `DELETE`/`retention`
admin note.

## API overview

Version prefix: **`/v1`**. JSON request/response. Envelope body = Chronicle
`Envelope.model_dump()` (JSON), including `attributes`, `start_time`, `parent_envelope_id`.

### Health

```http
GET /health
→ 200 {"status":"ok","version":"<plane-version>"}
```

Unauthenticated liveness for probes. Optional `GET /ready` that checks DB/queue.

### Ingest (agents)

#### Single

```http
POST /v1/envelopes
Authorization: Bearer <agent_key>
Content-Type: application/json
Idempotency-Key: <optional>
Durability: sync | queued   # optional; default sync

<Envelope JSON>

→ 201 {
    "status": "stored",
    "envelope_id": "...",
    "trace_id": "...",
    "durability": "sync"|"queued",
    "deduped": false
  }
→ 200  (same body, deduped: true)
→ 400  invalid envelope
→ 401 / 403
→ 413  payload too large
→ 429  rate limited
→ 503  store/queue unavailable (agent may retry or drop per policy)
```

#### Batch (preferred)

```http
POST /v1/envelopes:batch
Authorization: Bearer <agent_key>
Content-Type: application/json
Idempotency-Key: <optional-batch-key>
Durability: sync | queued

{
  "envelopes": [ <Envelope>, ... ]
}

→ 201 {
    "status": "stored",
    "accepted": 32,
    "deduped": 0,
    "envelope_ids": ["...", ...],
    "durability": "queued"
  }
```

Partial failure policy (v1): **all-or-nothing** for a batch under `sync` (transaction);
under `queued`, all messages accepted to the queue or none. Avoids ambiguous agent
retry logic. Cap `envelopes.length` (e.g. 100).

### Query (dashboard / TokenOps)

All require `read` (or stronger) scope.

```http
GET /v1/traces/{trace_id}
→ 200 {
    "trace_id": "...",
    "attributes": {"session_id":"...","message_id":"..."},
    "span_count": 7,
    "start_time": "...",
    "end_time": "..."
  }

GET /v1/traces/{trace_id}/envelopes
→ 200 { "envelopes": [ ... ] }   # ordered by sequence

GET /v1/traces/{trace_id}/envelopes/{envelope_id}
→ 200 { "envelope": { ... } }

GET /v1/traces?session_id=...&message_id=...&user_id=...&limit=50&cursor=...
→ 200 {
    "traces": [ { "trace_id", "attributes", "start_time", "end_time" }, ... ],
    "next_cursor": "..."
  }
```

Notes:

- Filter params match **envelope/trace attributes** written by `record(..., attributes=...)`.
- `message_id` alone should be unique enough within a tenant for feedback → trace.
- List endpoints are paginated; never unbounded `GET /envelopes` in production
  (deprecate the reference server’s full dump).

### Admin (optional v1.1)

Key rotation, retention policy, tenant config — not required to ship ingest+query.

## Compatibility with Chronicle clients

| Client | Change |
|---|---|
| `RemoteStore.append` | Point at `/v1/envelopes`; keep Bearer header. Prefer teaching `BufferedStore` → batch endpoint (extend RemoteStore with `append_many` → batch). |
| `open_store("https://…")` | Same URL; plane serves `/v1`. |
| Local JSONL/SQLite | Unchanged. |
| OTel / Phoenix | Unchanged optional export; not the system of record for envelopes. |

Migration: plane can temporarily accept legacy `POST /envelopes` as an alias of
`POST /v1/envelopes`.

## Data model (store)

Logical tables (illustrative):

- `tenants(id, …)`
- `traces(tenant_id, trace_id, attributes jsonb, start_time, end_time, …)` unique `(tenant_id, trace_id)`
- `envelopes(tenant_id, envelope_id, trace_id, sequence, parent_envelope_id, attributes jsonb, body jsonb, start_time, end_time, …)` unique `(tenant_id, trace_id, envelope_id)`
- Indexes: `(tenant_id, trace_id, sequence)`, `(tenant_id, (attributes->>'session_id'))`, `(tenant_id, (attributes->>'message_id'))`

`body` holds the full envelope JSON for fidelity; projected columns support query and
waterfall assembly.

## Security notes

- Never log full envelope bodies at info level (may contain prompts / PII); redact or
  sample.
- Rate limit per API key.
- Size limits on `attributes` values (e.g. 1 KiB per key) to protect indexes.
- Tenant isolation enforced in every query (`WHERE tenant_id = :t`).

## Open questions

1. **Default durability** for AgentPlane-hosted plane: `sync` vs `queued`?
2. **Batch-only** hot path — should single POST be discouraged in docs?
3. Should TokenOps ledger events share this API host under `/v1/ledger/…` (#30) or a
   sibling service with the same auth tenancy?
4. Soft delete / retention job cadence and legal hold.
5. Whether `RemoteStore` gains a **strict** mode that raises (or retries) instead of
   warn-and-drop for customers who choose durability over fail-open.

## Acceptance criteria (for an implementing PR / service)

- [ ] Spec frozen for `/v1` ingest (single + batch) and query (trace, envelopes, attributes filter)
- [ ] Auth enforced (Bearer scopes + tenant binding); reference server updated or replaced
- [ ] Durability modes documented and tested (`sync` commit, `queued` durable produce)
- [ ] Idempotent ingest on `(trace_id, envelope_id)`
- [ ] Load smoke: batch ingest under concurrency without duplicate rows
- [ ] Chronicle `RemoteStore` (and ideally `append_many`) documented against `/v1`
- [ ] Dashboard can resolve `session_id` + `message_id` → `trace_id` via query API

## References

- `chronicle/envelope/backends.py` — `RemoteStore`, `BufferedStore`, `SqliteStore`
- `examples/control_plane/server.py` — current unauthenticated reference
- Envelope schema — `attributes`, `start_time`, `parent_envelope_id` (OTel-aligned)
- Issue #30 — shared control plane package topology
- Issue #40 — attribution dims; lookup owned by plane/dashboard
