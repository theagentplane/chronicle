# Chronicle Technical Design: primitives to capabilities

| Field | Value |
|---|---|
| Status | Draft for review (not implemented) |
| Baseline | chronicle 0.5.0, control-plane 0.2.x, tokenops (read from source) |
| Scope | Chronicle, the shared primitives package, and the side effects on control-plane and TokenOps |
| Supersedes | `docs/rfcs/control-plane-api.md` (moves to the control-plane repo, see section 10) |

Sections that describe what exists today are marked **Today**. Everything else is the design.
Items deliberately not designed yet are marked **Future scope** and collected in section 12.

---

## 0. Status, scope and how to read this

Chronicle is an **edge component** (it runs inside the agent's own process and does no storage or viewing; see [P2](#13-principles)). It does three things: **record** what the agent
did at each decision point (a [boundary](#12-glossary-one-word-per-concept)), **save** it to the **control plane** (the separate, shared HTTP service that stores traces and serves queries and visualization), and **replay** a recorded request so a fix can be tested
without live LLM calls ([section 7](#7-capability-replay)).

It does not visualize, export to OTel (OpenTelemetry, the industry tracing standard), or store anything locally. Those belong to the control plane.

Three repositories have to work together at the end of this sprint:

| Repo | Role |
|---|---|
| `primitives` (new) | The shared schemas (entities defined in [section 2](#2-primitives)): Trace, Span, Envelope, API models, and the `traceparent` carrier (the helper for the W3C trace-context header, [section 3.2](#32-propagation-traceparent)). No I/O (no network or disk). |
| `chronicle` | Edge SDK: record, save, replay. Depends on `primitives`. |
| `control-plane` | Owns storage, query, visualization, export. Depends on `primitives`. |
| `tokenops` | Governance (budgets and spend policies for agent runs). Consumes Chronicle [hooks](#44-hooks). Side effects listed in [section 10](#10-cross-repo-side-effects). |

The document builds upward: principles (1), primitives (2), identity (3), in-process framework (4), repositories (5),
capabilities (6, 7), interfaces (8), configuration (9). Sections 10 to 12 hold side effects, the decision log, and what
is deliberately left out.

---

## 1. Principles and glossary

### 1.1 Layers

Each layer depends only on the ones above it in this list.

| Layer | Contains | Rule |
|---|---|---|
| **Primitives** | Trace, Span, Envelope and the API models | Data only. No I/O, no behaviour, no OTel. Owned by the primitives repo. |
| **Framework** | [Interceptor](#41-boundary-and-the-interceptor), [kind registry](#42-kind-registry), [adapters](#43-provider-and-tool-adapters), [hooks](#44-hooks), [redaction](#45-redaction), [context](#46-context-and-the-recording-session) | In-process machinery. No network. |
| **Repositories** | How entities are saved to and read from the control plane | The only layer that does I/O. |
| **Capabilities** | Record, Replay | Workflows built from the layers above. Own their logical (in-memory) objects. |
| **Interfaces** | Python SDK, framework instrumenters ([section 8](#8-interfaces)), config ([section 9](#9-configuration)) | What the developer touches. |

### 1.2 Glossary (one word per concept)

- **Boundary**: a declared decision point in user code, with a name and a kind (`llm` or `tool`; see [2.3](#23-input-and-output-by-kind)).
- **Crossing**: one execution of a boundary.
- **Envelope**: the persisted record of one crossing.
- **Span**: one service's handling of a request, i.e. one agent run in one process. The unit of replay ([7.1](#71-scope)).
- **Trace**: one request end to end, across services.
- **Metadata**: key/values describing an entity (placement rule in [2.3](#23-input-and-output-by-kind)).
- **Session modes**: `RECORD` (capture, [section 6](#6-capability-record)) and `REPLAY` (serve from a recording, [section 7](#7-capability-replay)).
- **Boundary modes in REPLAY**: `STUB` (return the recording, do not run) and `RUN` (execute real code).
- **Cut-point**: a REPLAY session where one or more boundaries are `RUN` and the rest are `STUB`.
- **Hook**: a user or integration callback that runs around a crossing ([4.4](#44-hooks)).
- **Control plane**: the shared HTTP service (separate repo) that stores traces, serves queries, and owns visualization and export.
- **Mint**: generate a new random id.
- **Adapter**: translates between a provider's or tool's own shape and Chronicle's canonical shape ([4.3](#43-provider-and-tool-adapters)).
- **Instrumenter**: a one-line integration that wraps a web framework or HTTP client to read or write trace context ([8.2](#82-input-integration-requests-entering-the-service), [8.3](#83-output-integration-calls-leaving-the-service)).
- **Recording session**: the in-memory object that records one span ([4.6](#46-context-and-the-recording-session)).
- **Cursor**: a per-boundary-name counter pointing at the next recorded envelope during replay ([7.3](#73-stub-internals-and-fidelity)).
- **Wire**: what is sent over HTTP to the control plane, as opposed to what is stored.
- **Upsert**: create if absent, otherwise update.
- **Idempotent**: repeating the call has no further effect.
- **Fail-open / strict**: when a dependency such as the control plane is unreachable, fail-open carries on without it and strict fails the operation ([3.3](#33-trace-creation-synchronous)).

**Today** the word "live" means both the recording mode and a boundary that runs real code during replay. This design
retires it in favour of `RECORD` and `RUN`.

### 1.3 Principles

- **P1. Own the schema; adapt to OTel elsewhere.** Chronicle's schema is not shaped around OpenTelemetry. W3C-compatible
  id formats and `traceparent` propagation (the W3C trace-context header, [section 3.2](#32-propagation-traceparent)) are kept because they cost nothing and keep distributed tracing interoperable.
  Any mapping to OTel is the control plane's job.
- **P2. Chronicle is an edge component.** Record, save, replay. Anything that is a view, an export or a store belongs to
  the control plane.
- **P3. Transparency.** Chronicle never changes what the wrapped function returns or raises, except where a hook
  deliberately aborts (section 4.4).
- **P4. Entities are closed in structure, open in content.** A fixed set of sections per entity; extension happens inside a
  section (a new metadata namespace, or a new member of the closed `kind` enum, see [2.3](#23-input-and-output-by-kind)), not by adding ad hoc fields.
- **P5. The control plane owns the entity schema.** Chronicle imports it from the primitives package; it does not define
  its own copy.

---

## 2. Primitives

These are the persisted entities. Their schemas live in the `primitives` repo, not in Chronicle (principle P5).

### 2.1 The three tiers

```
Trace  (one request, many services)
 └─ Span   (one service's handling of it; one process, one agent run)
     └─ Envelope   (one boundary crossing inside the span)
```

**Why three and not two.** OpenTelemetry has only spans, used both for a request at a service edge and for each action
inside it. Splitting them gives:

- **Replay and tests have a natural unit**: a Span, identified by `trace_id` plus `span_id`.
- **Parallel runs do not interfere.** Two concurrent agent runs append to their own spans.
- **Ordering becomes local.** `sequence` and `invocation_index` are counters inside one span (defined in [4.6](#46-context-and-the-recording-session)), so no distributed
  ordering problem exists (**Today** they are per-process counters that replay assumes are global).
- **Retention and ownership attach cleanly** to a span.

The cost is one extra entity and one extra id. In OTel terms a Chronicle Span maps to a server span and an Envelope to a
child span; that mapping is the control plane's concern.

**Cross-service link.** A Span's parent is the Envelope in the caller's span that made the outbound call
(`parent_envelope_id`). That is the only link between services. An outbound call to another agent is just a tool
envelope (see 2.3).

### 2.2 Entities

**Trace**

| Field | Notes |
|---|---|
| `trace_id` | 128-bit, 32 lowercase hex, W3C compatible (see [3.1](#31-ids)) |
| `name` | Optional human label |
| `metadata` | Trace-level labels, written once (see 2.6) |
| `state` | `open` or `closed`. Derived: open while any of its spans is open. A trace has no status of its own (OTel does not either); "did it succeed" is a view the control plane can compute. |
| `started_at`, `ended_at` | Derived by the control plane |

**Span**

| Field | Notes |
|---|---|
| `span_id` | 64-bit, 16 hex. Minted by the span's own service. |
| `trace_id` | |
| `parent_envelope_id` | `null` for the first span in a trace |
| `service` | Service or agent name |
| `state` | `open` or `closed` |
| `status` | `success` or `failure`, set when the span closes. Set by the entry point: `failure` if the request handler raised, otherwise `success`. Independent of envelope failures (a handled retry does not fail the span). |
| `started_at`, `ended_at` | |
| `metadata` | Span-level setup |

**Envelope**

```
Envelope
  schema_version
  identity         envelope_id, span_id, trace_id, parent_envelope_id, name, kind, attempt, links
  envelope_status  state (open | closed), status (success | failure), started_at, ended_at
  input            kind-specific (2.3)
  output           kind-specific (2.3), including error
  metadata         namespaced setup that is constant in code
```

- Every enumerated value and every reserved metadata key in these entities is listed in [2.9](#29-enumerations-and-well-known-keys).
- `kind` is defined in [2.3](#23-input-and-output-by-kind); `attempt` and `links` in [2.5](#25-links-retries-and-fan-in); `state` and `status` in [2.4](#24-lifecycle-one-record-mutable-until-closed) and below; `schema_version` in [2.8](#28-versioning-and-the-primitives-repo).
- **Today** the envelope is flat (`attributes` holds model, sampling and trace labels under OTel keys; `status` and
  timing are separate; `Message`, `ToolCall`, `Usage` and `LLMOutput` are sub-models of input/output).
- Extending the envelope with a new sibling section is an **additive, optional** change (minor schema bump). Anything
  narrower is a new payload variant or a new metadata namespace.
- Status has two values only: `success` and `failure`. There is no separate `aborted` status: a deliberate abort by a hook is a `failure` whose reason is recorded in `output.error` (`type = "AbortCall"`; `AbortCall` is the exception a hook raises to stop a call on purpose, see [4.4](#44-hooks)).
- Error information belongs to **output**, not metadata. `envelope_status.status` carries only the high-level result.

### 2.3 Input and Output by kind

Only two kinds exist: `llm` and `tool`. `kind` is a **closed enum defined in the primitives package**: there are no
unregistered or custom kinds, and a value outside the enum is rejected at validation. A router is an LLM call or, if it is
a function, a tool. **Today** `kind` is a free string and `router` and `custom` are also in use; they are retired
(migration in section 12). Adding a kind is a schema change made in primitives ([2.8](#28-versioning-and-the-primitives-repo)).

Input and Output are each a variant chosen by `kind`:

**`kind = tool`** (a method; arbitrary shape)

```
input   { raw: { ...bound arguments by name... } }
output  { raw: <JSON, the return value>, error?: { type, message } }
```

For a tool the canonical view is the raw data itself, so it is stored once.

**`kind = llm`**

```
input   { model, messages[], system?, tools?, tool_choice?, response_format?,
          params { temperature, top_p, max_tokens, seed, stop },
          raw (the arguments exactly as passed to the boundaried method, JSON) }
output  { content[] (text | tool_call | reasoning | refusal blocks),
          finish_reason,
          provider, model, model_source (served | requested),
          usage { input, cached_read, cache_write, output, reasoning },
          response_id, deployment_id?,
          raw (the value returned by the boundaried method, JSON),
          error? }
```

`usage` is part of **output**: it is returned by the provider as part of the response.

**Raw is always stored, for every kind.** `input.raw` and `output.raw` hold the input and output of the boundaried method
exactly as they crossed the boundary (in JSON form), and are never discarded. The canonical fields (for `llm`) are derived
from the raw data and used for all internal plumbing (cost, display, queries). The cost is accepted: for `llm` envelopes
the payload is roughly double. Benefits: replay needs no reverse mapping (see [7.3](#73-stub-internals-and-fidelity)), and
canonical fields can be re-derived later if an adapter is fixed. Redaction applies to raw as well
([4.5](#45-redaction)).

**Upfront contract: boundary inputs and outputs must be JSON-serializable.** Raw is the JSON form of the value, so
Chronicle can only store what converts to JSON. Common cases convert automatically (JSON-native values, pydantic models,
dataclasses). Anything else is stored as its text `repr`, which replay cannot restore. Users are told this rule up front in
the documentation. Hardening around it (a visible loss marker, a strict mode, per-boundary serializers) is future scope
(see 12.1).

**Fixed homes for pricing consumers.** SDKs do not share a structure: field names differ; cached tokens are counted
inside the input total by OpenAI but separately by Anthropic; the provider is usually not in the response at all;
and some SDKs (Bedrock Converse) do not return the served model. So the canonical fields below are filled by the [adapter](#43-provider-and-tool-adapters) and **do not change with the SDK or agent framework**. A consumer such as TokenOps reads only these, from `output`:

| Field | Meaning |
|---|---|
| `output.provider` | Who served the call (`openai`, `anthropic`, `azure`, `litellm`, ...). From the SDK or client type, or from the gateway when it reports one; `unknown` otherwise. |
| `output.model` | The model that served the call. If the response has none, the adapter copies the requested model and sets `model_source = requested`. |
| `output.usage` | **Exclusive, additive buckets**, the same for every provider: `input` (non-cached input), `cached_read`, `cache_write` (where reported), `output` (non-reasoning output), `reasoning`. The total is the sum, and each bucket is priced once. The adapter converts provider conventions; the consumer does not. |
| `input.model` | What the caller asked for, kept for reference. |

**Known hole.** A custom function wrapped with `@boundary(kind="llm")` and no adapter has an unknown return shape. Its
envelope carries `usage = null` and `provider = unknown`; consumers must tolerate null, or the developer supplies an
extractor hook ([4.3](#43-provider-and-tool-adapters)).

**What goes where (the rule).** This resolves the model/provider overlap:

| Where | What | Example |
|---|---|---|
| **Input** | Passed by the caller on this call | Requested model or alias, temperature, messages, tools |
| **Output** | Known only from the response | Served model version, provider or deployment id, response id, usage |
| **Metadata** | Constant setup in code, not in the call arguments | Client library and version, `base_url`, gateway, defaults baked into the client config |

Example with a LiteLLM Router (LiteLLM is a library that routes calls across LLM providers). The requested alias and the served deployment differ because of load balancing and
fallbacks (the router exposes the serving deployment on the response):

```
input.model      "gpt-4o"                        (the alias the caller asked for)
output.provider  "litellm"
output.model     "azure/gpt-4o-2024-08-06"       (what served it)
output.deployment_id  "<router deployment id>"
metadata         { client.library: "litellm", client.version: "..." }   (static setup only)
```

Pricing consumers (TokenOps) read provider, served model and usage from output. Metadata holds only static client
identity (library, version, `base_url`, defaults baked into the client config); model and provider are not duplicated there.

### 2.4 Lifecycle: one record, mutable until closed

An envelope is a **single record that is mutable until it is closed**.

- At **open**, identity and input are written; `state = open`.
- At **close**, output and `envelope_status` are written; `state = closed`. A closed envelope is immutable.
- In storage there is one record per envelope. On the wire (what is sent over HTTP to the [control plane](#12-glossary-one-word-per-concept)) there can be an open write and a close write.
- **`emit_open` is a config setting** (group *Intent capture* in [section 9](#9-configuration)) and is **opt-in** (default off). By default only the close write is sent (one write per envelope). Anything that needs the
  input before the call completes (for example [intent capture](#63-intent-capture)) enables `emit_open`.
- A Span follows the same open and close lifecycle.

**Known limitations (accepted for now).** There is no timeout-based `unfinished` state.

- With `emit_open` off, a crash mid-call loses that envelope entirely.
- With `emit_open` on, a crash leaves the envelope open indefinitely.

### 2.5 Links, retries and fan-in

- **Nesting**: `parent_envelope_id` within a span.
- **Parallel work**: siblings under the same parent, ordered by `envelope_status.started_at`.
- **Retries are declared explicitly.** Chronicle cannot know that a second call is a retry. A retry inside a provider SDK
  (for example `max_retries`) is invisible: one crossing. An app-level retry loop declares itself, for example with a
  context manager `chronicle.attempt(2, of=<previous envelope id>)`, which sets `attempt` and a `retry_of` link. No
  heuristic inference.
- **Fan-in** (an envelope that joins several parallel results) is **Future scope**.

Illustrative payloads (draft shapes, not final):

```json
{
  "envelope_id": "00f067aa0ba902b7", "span_id": "a1b2c3d4e5f60718",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "parent_envelope_id": null, "name": "agent.chat", "kind": "llm", "attempt": 1,
  "envelope_status": {"state": "closed", "status": "failure",
                      "started_at": "2026-10-02T10:00:00Z", "ended_at": "2026-10-02T10:00:01Z"},
  "input":  {"model": "gpt-4o", "messages": [{"role": "user", "content": "..."}]},
  "output": {"error": {"type": "RateLimitError", "message": "429 Too Many Requests"}}
}
```

```json
{
  "envelope_id": "b7ad6b7169203331", "span_id": "a1b2c3d4e5f60718",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "parent_envelope_id": null, "name": "agent.chat", "kind": "llm", "attempt": 2,
  "links": [{"type": "retry_of", "envelope_id": "00f067aa0ba902b7"}],
  "envelope_status": {"state": "closed", "status": "success",
                      "started_at": "2026-10-02T10:00:02Z", "ended_at": "2026-10-02T10:00:04Z"},
  "input":  {"model": "gpt-4o", "messages": [{"role": "user", "content": "..."}]},
  "output": {"content": [{"type": "text", "text": "..."}], "finish_reason": "stop",
             "usage": {"input": 812, "cached_read": 0, "cache_write": 0, "output": 96, "reasoning": 0},
             "provider": "openai", "model": "gpt-4o-2024-08-06", "response_id": "chatcmpl-9x..."}
}
```

### 2.6 Trace metadata

Trace-level labels live **once on the Trace**, not copied onto every envelope.
**Today** they are copied onto every envelope's `attributes`, and the labels are recovered by intersecting all envelopes
(`ExecutionGraph.attributes`); the Trace entity removes that workaround.

Chat-style applications often need `session_id`, `message_id` and `user_id`. These are **well-known Trace metadata keys**:
documented, first-class for users, but not core fields. Labels are write-once. The full list of well-known keys and the
metadata conventions are in [2.9](#29-enumerations-and-well-known-keys).

### 2.7 What is not a persisted entity

`ReplayPlan` ([7.2](#72-modes)), the recording session ([4.6](#46-context-and-the-recording-session)), the call log, captured inputs and results, and every view (graph, waterfall,
summaries). These are logical objects created inside a workflow, or views owned by the control plane. A "fixture" is not
an entity either: it was a trace exported to a directory, and fixtures in code are removed.

### 2.8 Versioning and the primitives repo

**Repo.** `theagentplane/primitives`. PyPI `agentplane-primitives`. Import `agentplane_primitives`. Contents: the
models above, id generation and validation, the `traceparent` carrier (the helper that parses and writes the header, [3.2](#32-propagation-traceparent)), the API request and response
models, and JSON Schema export (committed, with a CI drift check: a check that fails if the committed schema differs from what the models generate). Dependencies: pydantic only. No I/O. Python 3.10+.

**Two versions.**

- The package follows SemVer (semantic versioning: major.minor.patch).
- Every payload carries `schema_version` (`major.minor`). The package major equals the schema major.

**Rules.**

- **Additive-only within a major.** New optional fields are allowed, and readers ignore unknown fields. New members of a
  closed enum (including a new `kind`) are also additive for the writer, but a reader on an older minor rejects the unknown
  value, so consumers must upgrade before emitters (see the release order below).
- **Breaking change = new major.** The control plane accepts the current and the previous major and upconverts on read.
- **Release order for a breaking change:** primitives, then control plane (reads both), then Chronicle and TokenOps
  (emit the new one).
- **Pre-1.0:** consumers pin the exact minor. From 1.0: `>=1.2,<2`.
- **Safety net:** consumers import the primitives models instead of writing their own parsers, so they validate against the same code. A shared golden corpus of example payloads is future scope (12.1).

### 2.9 Enumerations and well-known keys

Every closed set of values and every reserved key in the entities above, in one place. The primitives repo carries the same
tables as field descriptions in the schema ([2.8](#28-versioning-and-the-primitives-repo)). **Open** means the set can grow
without a schema change; **closed** means a new value is a schema change.

**Enumerations**

| Name | Where | Values | Open or closed |
|---|---|---|---|
| `kind` | Envelope | `llm`, `tool` | Closed. Defined in primitives; no custom kinds. A new kind is a schema change ([2.3](#23-input-and-output-by-kind), [2.8](#28-versioning-and-the-primitives-repo)). |
| `state` | Trace, Span, Envelope | `open`, `closed` | Closed |
| `status` | Span, Envelope (not Trace) | `success`, `failure` | Closed. A deliberate abort is a `failure` with `output.error.type = "AbortCall"`. |
| `error.type` | `output.error` | The exception class name; reserved value `AbortCall` (a hook stopped the call on purpose) | Open |
| `links[].type` | Envelope | `retry_of`. `joined` (fan-in) is reserved for future scope. | Open |
| `model_source` | LLM output | `served` (the response named the model), `requested` (the adapter copied the requested model) | Closed |
| `provider` | LLM output | Well-known: `openai`, `anthropic`, `azure`, `google`, `bedrock`, `litellm`; `unknown` when it cannot be determined | Open |
| `finish_reason` | LLM output | Proposed canonical set: `stop`, `length`, `tool_calls`, `content_filter`, `other`. The provider's original value stays in `raw`. | Closed (proposal) |
| `content[].type` | LLM output | `text`, `tool_call`, `reasoning`, `refusal` | Closed |
| `messages[].role` | LLM input | `system`, `user`, `assistant`, `tool` | Closed |
| Session mode | Recording session | `RECORD`, `REPLAY` ([1.2](#12-glossary-one-word-per-concept)) | Closed |
| Boundary mode | Replay plan | `STUB`, `RUN` ([7.2](#72-modes)) | Closed |
| Hook event | Hooks | `enter`, `leave`, `crossing`, `record` ([4.4](#44-hooks)) | Closed |
| Config enums | Config | `trace_registration`: `sync`, `lazy`. `on_overflow`: `drop`, `block`. See [section 9](#9-configuration). | Closed |

`usage` buckets are fixed fields, not an enum: `input`, `cached_read`, `cache_write`, `output`, `reasoning`
([2.3](#23-input-and-output-by-kind)).

**Well-known Trace metadata keys** (labels on the Trace, written once; [2.6](#26-trace-metadata))

| Key | Meaning | Typical source |
|---|---|---|
| `session_id` | The user's conversation or session | Chat applications |
| `message_id` | The single message or turn that started the request | Chat applications; lets feedback be traced back to a trace |
| `user_id` | The end user | The application |

These are documented and first-class for users, but they are not fields on the entity. The control plane may index them.
Other keys are free-form.

**Metadata conventions (all entities)**

- Keys are lowercase, dot-separated (`client.library`). The `chronicle.` prefix is reserved for keys Chronicle itself sets;
  user keys must not use it.
- **Trace labels have string values** (they are indexed and filtered on). Span and Envelope metadata values may be any JSON
  value.
- Unknown keys are preserved on read and write.

**Well-known Envelope metadata keys** (static client identity only; [2.3](#23-input-and-output-by-kind))

| Key | Meaning |
|---|---|
| `client.library` | The client library in use (`openai`, `anthropic`, `litellm`, ...) |
| `client.version` | Its version |
| `client.base_url` | The endpoint it talks to, when not the default |
| `client.defaults` | Defaults baked into the client config rather than passed per call (object) |

No Span-level keys are defined yet.

---

## 3. Identity and propagation

### 3.1 Ids

| Id | Size | Minted by | Unique within |
|---|---|---|---|
| `trace_id` | 128-bit (32 hex) | First Chronicle-aware service on the request path | Globally |
| `span_id` | 64-bit (16 hex) | The span's own service | A trace |
| `envelope_id` | 64-bit (16 hex) | The recording service | A **trace** |

Envelope ids are random and treated as unique within a trace (collision odds are negligible: about 10^-12 for 10^4
envelopes). That is what lets `trace_id` plus `envelope_id` identify any envelope.

### 3.2 Propagation: `traceparent`

Chronicle uses the W3C header: `00-<trace_id>-<parent-id>-<flags>`.

- The `parent-id` field carries the **caller's outbound-call envelope id**.
- The parent *span* id is not passed: the control plane resolves envelope to span. If ever needed, `tracestate` can carry
  it.
- A service that receives a valid `traceparent` **joins** that trace and opens a new span whose `parent_envelope_id` is
  the received id. A service without one **mints** a new trace.

Two-service example:

```
Service A (span SA)                          Service B (span SB)
  envelope E1  llm  agent.chat
  envelope E2  tool http POST B/run  ──►  traceparent: 00-<trace>-<E2>-01
                                              span SB opens, parent_envelope_id = E2
                                              envelope F1  tool search ...
```

A delegate (an agent handing work to another over HTTP) is simply E2: a **tool** envelope. No separate kind.

### 3.3 Trace creation: synchronous

The first Chronicle-aware service mints the `trace_id` and **registers it on the control plane synchronously**
(idempotent, meaning repeating the call has no further effect; client-supplied id; labels write-once; a repeat call returns the existing trace).

- Only the first service on the path pays; downstream services that receive a `traceparent` join an existing trace.
- **Failure policy:** if the control plane is unreachable, a config flag decides: default **fail-open** (carry on without registration: continue with the
  locally minted id and let the control plane create the trace on first ingest) or **strict** (fail the request).
- **Switchable later:** a config setting `trace_registration: sync | lazy`, so a move to lazy needs no API change.
- **Measure first:** p50 and p99 latency added at the trace root, with the control plane local and remote. The result
  decides the follow-up.
- Span registration is asynchronous: a span's existence is implied by its first envelope.

### 3.4 Events

Queues and webhooks are **Future scope**. The carrier reserves `to_event` and `from_event` names (a CloudEvents-style (CloudEvents is a CNCF event-format specification)
tracing extension is the likely shape), documented but unimplemented.

---

## 4. Framework (in-process machinery)

### 4.1 Boundary and the interceptor

A boundary is declared with `@boundary(name, kind=...)`, `wrap(client)`, `wrap_llm(name, fn)` or the LangGraph (an agent-graph framework)
instrumenters. All of them go through **one interceptor** that owns the crossing lifecycle (record, stub, run).

**Today** the lifecycle is copy-pasted about six times (boundary sync and async, record and cut-point, and `wrap` sync and
async). `wrap` also skips the pre-call hook and failure capture, and reads the session's private replay cursor. The
design has a single lifecycle used by every entry point, so `wrap` gains hooks and failure capture. That is a behaviour
change to call out in the migration note.

### 4.2 Kind registry

`kind` is a closed enum from the primitives package ([2.3](#23-input-and-output-by-kind)), so there are no unregistered
kinds. Behaviour per kind lives in one **strategy** (a small object implementing that kind's behaviour) per enum member
instead of `if` chains: how to capture input, how to build output, how to build the stub return value, and which metadata
to attach. Strategies exist for `llm` and `tool`. Adding a kind means adding it to the primitives enum and adding its
strategy; declaring a boundary with any other kind fails at declaration time.

### 4.3 Provider and tool adapters

Adapters translate between an external shape and the canonical shape.

| Direction | Status |
|---|---|
| Provider response to canonical LLM output (text, tool calls, usage, served model) | **Exists** for OpenAI-style and Anthropic-style clients (`wrap.py`, `genai.py`, `usage_from`) |
| Per-boundary shaping of input, result and metadata | **Exists** as hooks (`extract_input`, `extract_result`, `extract_metadata`) |
| Canonical back to the original return value, for replay | **Not needed**: the raw output is stored, so replay hands it back directly ([2.3](#23-input-and-output-by-kind), [7.3](#73-stub-internals-and-fidelity)). Today a fixed per-kind reverse mapping rebuilds it, which is what lost data. |

**Design.** An adapter is **one-way**, keyed by provider or tool: `to_canonical(raw)`. It derives the canonical fields from
the raw input and output, which are stored unchanged alongside. There is no `from_canonical`. Today's defaults become the
first adapters. Custom adapters are a later extension.

**How adapters link to kinds.** The kind strategy ([4.2](#42-kind-registry)) owns the workflow and delegates shape
translation to an adapter. The `llm` strategy requires one and enforces the contract below (without a match it records
`usage = null` and `provider = unknown`); the `tool` strategy uses the generic JSON path, and a tool adapter is an
optional override. Adapters are looked up by `(kind, provider-or-tool id)`; for LLMs the provider is detected from the
client type or given explicitly. A new provider is a new adapter with no change to the registry or the strategy.

**Adapter contract.** For `llm` boundaries an adapter must fill the fixed fields from 2.3 (`provider`, `model`,
`model_source`, exclusive `usage` buckets). Each supported provider has a conformance test in Chronicle's own test suite: a
golden raw response and its expected canonical form.

**Adapters in this sprint:** OpenAI-style (Chat Completions; also covers LiteLLM, which returns OpenAI-shaped responses)
and Anthropic-style, both already present in `wrap.py`. Target adapters for upcoming work are listed in 12.1.

### 4.4 Hooks

**One kind of hook.** A hook is a callback with these events: `enter` (before the call; may patch keyword arguments or
abort), `leave` (after, always, if `enter` succeeded), `crossing` (the call returned and was captured), `record` (the
envelope was written).

- **Ordering:** registration order. Patches returned from `enter` are merged in order; the later one wins.
- **Failure handling:** a global config flag decides whether a hook failure fails the call
  (`hooks.fail_call_on_error`, default **false**: log and continue).
- **Deliberate abort:** a dedicated `AbortCall` exception **always propagates**, regardless of the flag. This is how a
  governor (a governance component such as TokenOps) stops a call on purpose. Without it, "swallow failures" would silently disable governance.
- **After the function ran:** if the flag is true, an exception from `crossing`, `record` or `leave` fails the call even
  though the function already completed; that is why the default is false.
- Hooks are registered on a [session](#46-context-and-the-recording-session) or as defaults inherited by every new session. This replaces the practice of patching
  `reset_session` to re-attach callbacks.
- **Today** there are four single-slot callbacks on the session with no ordering, and exceptions from the post-call ones
  propagate after the function ran.
- **Security surface: Future scope.** Hooks currently see raw input before redaction and the live result object, and can
  change arguments. What hooks may see and do needs its own review.

### 4.5 Redaction

Prompts and responses are production data, and secrets must not leave the process, so redaction is applied **before
anything is sent**. It is a recorder step (the part of the [recording session](#46-context-and-the-recording-session) that builds and sends envelopes), not a general processing framework (other in-flight transforms such as
sampling or enrichment are not in scope).

- **Provided by:** the `redactors` config setting or `record(redactors=[...])`. A redactor is `str -> str`.
- **Default:** none (opt-in). `default_redactors()` is a helper that masks common secret shapes (API keys, tokens, JWTs,
  private keys).
- **Applied to:** every string value in input, output (including `raw`) and status messages. Keys are left alone so structure stays intact.
- **Extended by:** passing your own callables. **Disabled by:** passing none.
- Pattern-based redaction is a baseline, not a guarantee; PII needs your own redactors.

### 4.6 Context and the recording session

- **One recording session per span.** A trace can have many spans (in one process or several), each with its own session.
- The active envelope stack is context-scoped, so concurrent async requests and threads nest independently.
- **Counters** (both span-local):
  - `sequence`: start order of envelopes in the span.
  - `invocation_index`: "this is the n-th call of boundary X in this span". Replay uses it to match a recording.
- **Today** the session is a large object holding trace ids, the span stack, recording, redaction, the replay cursor,
  captured results and four callback slots. The design separates trace context, recorder, replay state and hooks.

---

## 5. Repositories

Chronicle has **one backend: the control plane, over HTTP.** No local stores, no JSONL, no SQLite, no fixtures in code.

### 5.1 Write side

Chronicle needs three writes:

| Write | Meaning |
|---|---|
| Upsert Trace | Create-if-absent with write-once labels (synchronous at the trace root, see 3.3) |
| Upsert Span | Open and close |
| Append Envelope | One write at close, plus an open write when `emit_open` is on |

- `append` is a **non-blocking enqueue** (the envelope is placed on an in-memory queue) with background batched flush (sent in groups). Flush also happens at span end and at shutdown.
  Batching is an internal detail of the client, not part of the contract.
- **Delivery policy** is explicit config: queue size, overflow behaviour (drop or block), timeout, and fail-open versus
  strict (see [3.3](#33-trace-creation-synchronous)). Because there is no local buffer on disk, a crash can lose queued items.

### 5.2 Read side

Only replay reads from Chronicle: **the envelopes of span S in trace T.** Whole-trace reads, envelope lookups and trace
listing are control-plane concerns and are not part of Chronicle's contract.

### 5.3 What this removes

The `open_store` target registry, the JSONL and SQLite stores, the buffered-store target syntax, `read_all`, and the
local reference server. **Today** the `Store` protocol requires `read_all` and `find_by_envelope_id`, which the remote
store cannot honour (it returns empty results that look like "no data"); the narrower contract removes that mismatch.

### 5.4 Test strategy

Chronicle's own tests use an **in-memory fake** of the repository, kept inside the test suite and not shipped as a
backend. The wire format is covered by the primitives models themselves, which Chronicle and the control plane both import.

### 5.5 Consequences accepted

- Replay needs a reachable control plane and a trace still within the control plane's retention.
- The zero-config local quickstart goes away; a control plane is required.
- The README's "commit the incident as a fixture" story changes to "replay a recorded trace by id".
- Chronicle's existing tests and examples that use fixtures, JSONL or the local server need rewriting.

---

## 6. Capability: Record

### 6.1 Workflow (one request)

1. **Entry.** An inbound request is intercepted by a framework instrumenter or the custom API ([section 8.2](#82-input-integration-requests-entering-the-service)).
   - A valid `traceparent` is present: **join** that trace, open a Span with `parent_envelope_id` set from it.
   - Otherwise **mint** a `trace_id`, register it synchronously (3.3), open the first Span.
2. **Per crossing** (inside the Span):
   1. Capture input. If `emit_open` is on, send the open write now.
   2. Run `enter` hooks (may patch arguments or abort).
   3. Call the wrapped function (sync or async).
   4. Build output (via the kind and adapter). On exception, record `status = failure` with error details in output and
      re-raise.
   5. Apply redaction.
   6. Close the envelope and enqueue the write.
   7. Run `crossing`, `record` and `leave` hooks.
3. **Outbound call to another service.** The outbound HTTP client is itself a [tool boundary](#23-input-and-output-by-kind). Its envelope id is injected as
   the `traceparent` parent (8.3).
4. **Exit.** Close the Span, flush the queue.

### 6.2 Failure semantics

- The caller always receives the real return value or the real exception (principle P3), except for an `AbortCall` raised
  deliberately by a hook.
- A failing crossing is recorded and re-raised, so incidents that raise are still reproducible.
- Recording failures (control plane unreachable, queue full) follow the delivery policy and never break the agent unless
  strict mode is on.

### 6.3 Intent capture

A separate project needs the envelope to exist **before** the call completes in order to track the input. This is the
open-record path: with `emit_open` on, the open write carries identity and input; the close write completes it.

### 6.4 Known limitations

- Crash mid-call: lost envelope (`emit_open` off) or an envelope left open (`emit_open` on). No `unfinished` state yet.
- A retry hidden inside a provider SDK is one crossing.

### 6.5 Future scope: streaming

**Today** streaming is not supported (the ROADMAP lists it as near-term); a streamed return would likely be recorded as
an empty or stringified output at call time. The open-then-close lifecycle is what allows a later design to close the
envelope when the stream ends, accumulate chunks into the canonical output (text, tool-call deltas, final usage), record
time to first token, record cancellation as partial output, and re-emit a recorded output as a stream on replay.

---

## 7. Capability: Replay

### 7.1 Scope

Replay is scoped to a **service request instance**: `trace_id` plus `span_id`. The test pulls the span's envelopes from
the control plane by those ids. There is no fixture directory and no promote-to-test step: the primitives are the
building blocks, and what a team checks in is up to them.

A span's outbound calls to other services are tool envelopes, so on replay they are stubbed with the recorded response;
the downstream span is not re-run. It can be replayed on its own.

### 7.2 Modes

- **STUB**: return the recorded output, do not run the function. No hooks fire.
- **RUN**: execute the real function. Nothing is written to the control plane; input and result are kept in memory so
  the test can assert on them. The cursor (a per-name counter pointing at the next recorded envelope) advances even if the call raises.
- A cut-point is a REPLAY session with at least one boundary on `RUN`.
- A **replay plan** (which boundary and which invocation is `STUB` or `RUN`) is a logical object, not an entity.

### 7.3 Stub internals and fidelity

For a stubbed call, Chronicle takes the next recorded envelope for that boundary name (cursor) and hands back its
**`output.raw`** directly. There is no reverse mapping from the canonical fields.

**Fidelity rule for this sprint: JSON outputs only.** The raw output is the method's return value in JSON form, so it must
be JSON-serializable (dict, pydantic model, dataclass). Replay hands back that JSON wrapped in a dict-like proxy so
attribute access works.

**What was wrong today** (so the design does not repeat it):

- `@boundary(kind="llm")` and `wrap_llm` only understand a dict with keys `completion`, `tool_calls`, `finish_reason`
  and `usage`. An SDK-object return is stored as its repr string, and replay then returns a state dict with
  `completion = None`. Extra keys in a dict return are dropped, and input arguments are echoed into the stub return.
- `wrap(client)` stores the complete response but replays it through a lookalike object.
- Tools store `str(result)` for anything non-JSON.

The requirement is met by storing the full input and return in lossless JSON (`raw`, [2.3](#23-input-and-output-by-kind))
and replaying from it. Rebuilding the original Python type from `raw` (for code that depends on `isinstance` or SDK
methods) is future scope.

### 7.4 Limitations (stated up front)

- **Matching is by name plus call count, not by input.** If a fix calls a tool with different arguments or in a different
  order, replay still returns the n-th recording of that tool.
- **Async tool calls.** Even with deterministic code, the order in which parallel calls start can change, so the call
  number can change, and the wrong recording can be served.
- **Non-JSON returns are not supported** (7.3).

### 7.5 Verification

The main flow is the supported one: replay your agent with boundaries intercepted, then assert on what the live code
returned (`captured_input` and `captured_result`: the input and return value of each `RUN` boundary, kept in memory).

- **Layer 1** (`ReplayInjector` and `StructuralAssertions`) is retired. It was a manual single-envelope harness that does
  not intercept boundaries and does not use the replay plan. Its three useful checks (tools called, argument keys,
  finish reason) can return later as assertion helpers.
- **Layer 2** (LLM-as-judge) is deferred.
- **TestCase** (a declarative test entity) is held.

---

## 8. Interfaces

### 8.1 Python SDK

`@boundary`, `wrap`, `wrap_llm`, `instrument(...)` for LangGraph, `record()` and `replay_trace()` style entry points,
`ReplayPlan`, `attempt(...)`, hook registration, and the custom propagation API. Exact signatures are settled during
implementation.

### 8.2 Input integration (requests entering the service)

| Mechanism | v1 | Later |
|---|---|---|
| ASGI (the async Python web interface) middleware (FastAPI, Starlette, any ASGI app) | yes | |
| Custom API: `chronicle.extract(headers)` plus `chronicle.span(parent=...)` for any other entry point (CLI jobs, workers) | yes | |
| WSGI (the sync Python web interface; Flask, Django), AWS Lambda, gRPC server, A2A (agent-to-agent protocol) servers, MCP (Model Context Protocol) servers | | yes |

MCP over stdio has no headers; the later design uses the JSON-RPC `_meta` field.

### 8.3 Output integration (calls leaving the service)

| Mechanism | v1 | Later |
|---|---|---|
| `httpx` (a Python HTTP client) instrumenter: records the call as a tool envelope and injects its id as the `traceparent` parent | yes | |
| Custom API: `chronicle.inject(headers)` inside a boundary-wrapped client function | yes | |
| `requests`, `aiohttp`, gRPC client, A2A client, MCP client | | yes |

**Propagation allow-list (security default).** LLM SDKs use `httpx` internally. Without a filter the header would be sent
to third parties such as `api.openai.com`, leaking trace ids and double-recording the call. Injection happens **only
to configured hosts**; the default is deny.

### 8.4 What the developer sees versus what is automatic

| Visible in code | Automatic |
|---|---|
| Install, env vars, one-line instrumenters, optional custom API | Join or mint trace, open span, record outbound calls, inject `traceparent`, flush |

Once the instrumenters are on, nothing more is required.

### 8.5 Removed

The CLI (`record`, `extract`, replay and judge commands; `extract` wrote fixture directories and `record` bootstrapped
Phoenix and OpenInference), the local reference server in `examples/control_plane/`, the visualizer and the
`ExecutionGraph` renderers, and the OTel exporter.

---

## 9. Configuration

Every setting a developer can set in their agent that Chronicle honors. **Precedence:** code, then environment
(`CHRONICLE_*`), then config file. **Today** only `CHRONICLE_ENABLED` exists. Names below are proposed.

| Group | Setting | Meaning |
|---|---|---|
| Core | `enabled` | Master switch for recording. Does not disable hooks. |
| | `control_plane_url`, `api_key` | Where and how to save |
| | `service_name` | Names the service on its spans |
| Capture | `capture_input`, `capture_output` | Toggles |
| | `max_payload_bytes` | Truncation limit |
| Redaction | `redactors`, `default_redactors` | See 4.5 |
| Propagation | `extract`, `inject` | On or off |
| | `inject_hosts` | Allow-list; default deny (see [8.3](#83-output-integration-calls-leaving-the-service)) |
| Hooks | `hooks.fail_call_on_error` | Whether a hook failure fails the call (default false). `AbortCall` always propagates. See [4.4](#44-hooks). |
| Delivery | `batch_size`, `flush_interval`, `max_queue` | Buffering |
| | `on_overflow` | `drop` or `block` |
| | `timeout`, `fail_open` | Network behaviour |
| Trace registration | `trace_registration` | `sync` (now) or `lazy` (later); see [3.3](#33-trace-creation-synchronous) |
| | `registration_fail_open` | Behaviour when the control plane is unreachable |
| Intent capture | `emit_open` | Send an open write for each envelope (default off); see [2.4](#24-lifecycle-one-record-mutable-until-closed) and [6.3](#63-intent-capture) |

Interaction to document with the code: with `enabled = false`, **today** boundaries become plain passthroughs and skip
hooks, so turning recording off also turns off governance. The design decouples hooks from the recording switch (open
question in section 12).

---

## 10. Cross-repo side effects

Each list is meant to be applied to that repo independently.

### 10.1 primitives (new repo)

1. Create `theagentplane/primitives` (`agentplane-primitives`).
2. Define Trace, Span, Envelope (with `llm` and `tool` input/output variants), the metadata rules, and the API models.
3. `traceparent` carrier (parse, format; reserved `to_event` and `from_event`).
4. Id generation and validation.
5. Committed JSON Schema with a drift check; versioning policy from 2.8.

### 10.2 control-plane

1. Depend on `primitives`; the control plane owns the schema, Chronicle inherits it.
2. Trace and Span entities. Idempotent `POST /v1/traces` (client-supplied id, write-once labels, repeat returns existing).
3. Span upsert (open and close). Envelope write supporting an open record updated at close.
4. Read endpoint: envelopes of span S in trace T (for replay).
5. Strict acknowledged ingest option and delivery semantics.
6. Rename `dims` to `metadata`; key envelopes by trace-unique envelope id.
7. Own visualization (waterfall, trace views), OTel export, and any export features. It already has a Chronicle tab with
   a trace list and waterfall; Chronicle's `visualizer.py` and `ExecutionGraph` renderers duplicate that and move.
8. Take over the HTTP API RFC currently at `chronicle/docs/rfcs/control-plane-api.md`.
9. Retention policy matters now, because tests read traces from the database.
10. Accept the current and previous schema major on ingest.

### 10.3 tokenops

1. Remove `delegate` from `NodeType` (TokenOps' list of observation kinds; now `llm | tool`); delegates become ordinary tool observations. Drop the
   `rolled_up_cost_micros` handling and the delegate branch in `ledger.py`. Spend is already booked once, in the child's
   LLM calls, so totals are unaffected.
2. Replace `X-TokenOps-Run-Id` and `X-TokenOps-Parent-Span-Id` with Chronicle's `traceparent`. How `run_id` relates to
   `trace_id` (equal, or a Trace label) is still to be decided.
3. Read `output.provider`, the served `output.model` and `output.usage` (`input`, `cached_read`, `cache_write`, `output`,
   `reasoning`; see [2.3](#23-input-and-output-by-kind)) from the envelope, rather than from the live result object.
4. Use the hook contract in 4.4: raise `AbortCall` to halt a call; stop patching `reset_session`; register as a default
   hook.
5. **In-flight counting stays in TokenOps for now.** Its `inflight` counter counts concurrent LLM calls through
   `admit` and `complete`, and is unaffected by this design. No Chronicle change for TokenOps at this time.
6. Spans registered by TokenOps with immutable labels before telemetry use the synchronous trace registration path.

### 10.4 chronicle (removals)

`chronicle/cli.py`, `visualizer.py`, `otel.py`, the OpenInference and Phoenix instrumentation, the JSONL and SQLite
stores and the `open_store` registry, `examples/control_plane/`, committed `fixtures/`, `ReplayInjector` and
`StructuralAssertions`, and `docs/rfcs/control-plane-api.md`. The judge module stays but is out of scope (deferred).

---

## 11. Decision log

| # | Decision | Reasoning |
|---|---|---|
| 1 | Envelope sections: identity, `envelope_status`, input, output, metadata. Input and output vary by kind. Placement rule in 2.3. | Keeps extension inside sections; removes the model/provider duplication; usage is returned by the provider so it is output. |
| 2 | Retries declared explicitly; fan-in deferred. | Chronicle cannot infer retries; fan-in is derivable from timing for now. |
| 3 | `traceparent` carries trace id plus the caller's envelope id; envelope ids unique per trace. | The pair identifies the parent; the parent span is derivable. |
| 4 | Trace registration is synchronous for now; measure, then reconsider. | Simplicity first; the setting makes the later switch cheap. |
| 5 | Single record, mutable until closed; `emit_open` (a config setting, [section 9](#9-configuration)) opt-in; no `unfinished` state yet. | Supports intent capture without doubling default traffic; the crash gap is accepted. |
| 6 | One kind of hook; global fail-call flag; `AbortCall` always propagates. | Keeps hooks simple while letting a governor stop a call deliberately. |
| 7 | v1 instrumenters: ASGI, `httpx`, custom API; allow-list default deny. | Minimum for the three repos; avoids leaking trace ids to third parties. |
| 8 | Remote-only; tests use an in-memory fake. | One backend; the control plane owns storage. Consequences listed in 5.5. |
| 9 | `theagentplane/primitives` and the versioning plan in 2.8. | The control plane owns the schema; Chronicle must not depend on server code. |
| 10 | JSON outputs only for stub fidelity; per-provider and per-tool adapters are one-way (`to_canonical`). | Rebuilding Python types is later work. |
| 20 | Raw input and output of the boundaried method are stored as-is for every kind; canonical fields are derived for internal plumbing; no `from_canonical`. | Replay needs no reverse mapping and loses nothing; canonical fields can be re-derived; the roughly doubled payload size is accepted. |
| 11 | Replay scoped to `trace_id` plus `span_id`; name-plus-count matching with documented limitations. | A span is the service request instance; matching improvements are future work. |
| 12 | Kinds: `llm` and `tool` only, as a closed enum in primitives; no custom or unregistered kinds. Delegate is a tool. | A router is an LLM call or a function; the delegate link is carried by `traceparent`. |
| 13 | Config surface in section 9. | One documented place for everything Chronicle honors. |
| 14 | Clean break from 0.5.0 (schema, remote-only, removals). | The change cannot be additive. |
| 15 | Order of work: primitives, control plane, Chronicle and TokenOps. | Each depends on the schema above it. |
| 16 | Chronicle does not change for TokenOps now; in-flight counting stays in TokenOps. | It counts concurrent LLM calls and does not depend on `delegate`. |
| 17 | Visualization, OTel export and export features belong to the control plane. | Chronicle is an edge component (P2). |
| 18 | Streaming, events, fan-in, TestCase, Layer 2, `unfinished` state: Future scope. | Not needed this sprint. |
| 19 | Fixed homes for LLM cost data: `output.provider`, `output.model`, `output.usage` (exclusive, additive buckets), filled by adapters ([2.3](#23-input-and-output-by-kind)). | TokenOps reads one place whatever the SDK or agent framework; adapters absorb provider differences. |

---

## 12. Limitations, future scope and migration

### 12.1 Future scope

- **Events** (queues, webhooks) and the event carrier.
- **Streaming** capture and replay (6.5).
- **Fan-in** links.
- **TestCase** entity and a pytest runner.
- **Layer 2** LLM-as-judge and assertion helpers.
- **`unfinished` state** with a timeout, and span-derived concurrency counting.
- **Rebuilding original Python types** from `raw` on replay (7.3).
- **Golden payload corpus** in the primitives repo: shared known-good and known-bad examples. Not needed while every consumer
  imports the shared models; worth adding if a consumer parses payloads without them.
- **Serialization hardening** (the JSON conversion behind `raw`, [2.3](#23-input-and-output-by-kind)). Today the conversion is
  lossy and silent: opaque objects become a `repr` string; dates, UUID, Decimal, Enum and bytes also fall through to
  `repr`; tuples and sets become lists; dict keys become strings; nesting deeper than 6 levels becomes `repr`; `NaN` and
  `inf` are not valid JSON. Planned:
  - A better converter (pydantic-style JSON conversion for dates, UUID, Decimal, Enum, bytes, sets).
  - Type-tagged values so common types round-trip (for example `{"$type": "datetime", "value": "..."}`).
  - A visible loss marker for anything that cannot be converted (`{"$unserializable": "ClassName", "repr": "..."}`) and a
    per-envelope flag (`chronicle.raw.lossy`).
  - A strict mode: a config setting `on_unserializable` (`mark` by default, never breaks the call; `raise` for development
    and CI, failing the first call with a clear message). This is where a serializer becomes mandatory, only when strict
    mode is on and only for the boundary that failed.
  - Per-boundary controls: a `serializer` (an adapter for a custom type, building on `extract_input` and `extract_result`)
    and `exclude=[...]` for injected dependencies such as clients and connections.
  - A declaration-time warning when a boundary's type annotations are clearly not serializable.
  - Replay failing loudly for a boundary flagged lossy, instead of returning mangled data.
  - Pickle is ruled out: it cannot be redacted and unpickling a recorded payload can run arbitrary code.
- **Redaction order and coverage** (notes for [4.5](#45-redaction) and [6.1](#61-workflow-one-request)). Redaction can only
  act on the JSON form, so the intended order is: convert to JSON, redact `raw`, derive the canonical fields from the
  redacted raw, then store. Section 6.1 currently lists building the output before redaction and needs reconciling. Metadata
  is not scrubbed today (for example a `client.base_url` with embedded credentials); coverage of metadata is to be decided.
- **Target adapters (not immediate):**
  - LLM: OpenAI Responses API, Azure OpenAI (deployment name versus underlying model), Google Gemini, AWS Bedrock Converse
    (no served model in the response), and chat-model wrappers such as LangChain and LangGraph at the SDK level.
  - Tools: HTTP calls (the `httpx` instrumenter's tool envelope shape), MCP tool calls, A2A calls.
- **Trace-context validation and trust:** how a downstream service decides to trust an inbound `traceparent`.
  - Today (W3C) only the format can be checked: malformed means ignore and mint a new trace. A well-formed header proves
    neither that the trace exists, nor that the parent envelope exists (it may not be flushed yet), nor that the sender is
    legitimate.
  - To design: guidance to turn `extract` off on internet-facing services (spoofed headers attach spans to someone else's
    trace id); control-plane tenant-scoped trace keys `(tenant, trace_id)` so a copied id cannot cross tenants; the control
    plane tolerating a dangling `parent_envelope_id`; and optional signed context (a signature carried in `tracestate`).
- **Hook security review**: what hooks may see and do (4.4).
- **More instrumenters** (8.2, 8.3).
- **Better replay matching** (by input fingerprint) to address async reordering (7.4).
- **Lazy trace registration** after the latency measurement (3.3).

### 12.2 Open items

- **Version number** of the clean break: 0.6 or 1.0.
- **`run_id` and `trace_id`** relationship for TokenOps (10.3).
- **Decoupling hooks from `enabled`** (section 9): proposed, not yet confirmed.
- **Enumerations to confirm (2.9):** the canonical `finish_reason` set, and string-only values for Trace labels.
- **Adding hooks that need sync registration for spans** if TokenOps requires it: spans are async for now.

### 12.3 Migration from 0.5.0

A clean break with one migration note:

- Envelope shape changes (flat to sections; `attributes` to `metadata`); `router` and `custom` kinds become `tool`.
- Local stores, fixtures, the CLI and the local server are removed.
- `wrap` now runs hooks and records failures.
- Existing fixtures under `fixtures/` are not replayable; re-record against the control plane.
- Hooks: the single-slot callbacks are replaced by the hook contract.
