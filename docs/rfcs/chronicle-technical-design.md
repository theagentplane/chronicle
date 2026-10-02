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

Chronicle is an **edge component** that lives inside an agent's process. It does three things: **record** what the agent
did at each decision point, **save** it to the control plane, and **replay** a recorded request so a fix can be tested
without live LLM calls.

It does not visualize, export to OTel, or store anything locally. Those belong to the control plane.

Three repositories have to work together at the end of this sprint:

| Repo | Role |
|---|---|
| `primitives` (new) | The shared schemas: Trace, Span, Envelope, API models, `traceparent` carrier. No I/O. |
| `chronicle` | Edge SDK: record, save, replay. Depends on `primitives`. |
| `control-plane` | Owns storage, query, visualization, export. Depends on `primitives`. |
| `tokenops` | Governance. Consumes Chronicle hooks. Side effects listed in section 10. |

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
| **Framework** | Interceptor, kind registry, adapters, hooks, redaction, context | In-process machinery. No network. |
| **Repositories** | How entities are saved to and read from the control plane | The only layer that does I/O. |
| **Capabilities** | Record, Replay | Workflows built from the layers above. Own their logical (in-memory) objects. |
| **Interfaces** | Python SDK, framework instrumenters, config | What the developer touches. |

### 1.2 Glossary (one word per concept)

- **Boundary**: a declared decision point in user code, with a name and a kind (`llm` or `tool`).
- **Crossing**: one execution of a boundary.
- **Envelope**: the persisted record of one crossing.
- **Span**: one service's handling of a request, i.e. one agent run in one process. The unit of replay.
- **Trace**: one request end to end, across services.
- **Metadata**: key/values describing an entity.
- **Session modes**: `RECORD` (capture) and `REPLAY` (serve from a recording).
- **Boundary modes in REPLAY**: `STUB` (return the recording, do not run) and `RUN` (execute real code).
- **Cut-point**: a REPLAY session where one or more boundaries are `RUN` and the rest are `STUB`.
- **Hook**: a user or integration callback that runs around a crossing.

**Today** the word "live" means both the recording mode and a boundary that runs real code during replay. This design
retires it in favour of `RECORD` and `RUN`.

### 1.3 Principles

- **P1. Own the schema; adapt to OTel elsewhere.** Chronicle's schema is not shaped around OpenTelemetry. W3C-compatible
  id formats and `traceparent` propagation are kept because they cost nothing and keep distributed tracing interoperable.
  Any mapping to OTel is the control plane's job.
- **P2. Chronicle is an edge component.** Record, save, replay. Anything that is a view, an export or a store belongs to
  the control plane.
- **P3. Transparency.** Chronicle never changes what the wrapped function returns or raises, except where a hook
  deliberately aborts (section 4.4).
- **P4. Entities are closed in structure, open in content.** A fixed set of sections per entity; extension happens inside a
  section (new kind payload, new metadata namespace), not by adding ad hoc fields.
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
- **Ordering becomes local.** `sequence` and `invocation_index` are counters inside one span, so no distributed
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
| `trace_id` | 128-bit, 32 lowercase hex, W3C compatible |
| `name` | Optional human label |
| `metadata` | Trace-level labels, written once (see 2.6) |
| `started_at`, `ended_at`, `status` | Derived or set by the control plane |

**Span**

| Field | Notes |
|---|---|
| `span_id` | 64-bit, 16 hex. Minted by the span's own service. |
| `trace_id` | |
| `parent_envelope_id` | `null` for the first span in a trace |
| `service` | Service or agent name |
| `started_at`, `ended_at`, `status` | |
| `metadata` | Span-level setup |

**Envelope**

```
Envelope
  schema_version
  identity         envelope_id, span_id, trace_id, parent_envelope_id, name, kind, attempt, links
  envelope_status  state (open | closed), outcome (success | error), started_at, ended_at
  input            kind-specific (2.3)
  output           kind-specific (2.3), including error
  metadata         namespaced setup that is constant in code
```

- **Today** the envelope is flat (`attributes` holds model, sampling and trace labels under OTel keys; `status` and
  timing are separate; `Message`, `ToolCall`, `Usage` and `LLMOutput` are sub-models of input/output).
- Extending the envelope with a new sibling section is an **additive, optional** change (minor schema bump). Anything
  narrower is a new payload variant or a new metadata namespace.
- Error information belongs to **output**, not metadata. `envelope_status.outcome` carries only the high-level result.

### 2.3 Input and Output by kind

Only two kinds exist: `llm` and `tool`. A router is an LLM call or, if it is a function, a tool. **Today** `router` and
`custom` are also kinds; they are retired (migration in section 12).

Input and Output are each a variant chosen by `kind`:

**`kind = tool`** (a method; arbitrary shape)

```
input   { arguments: { ...bound arguments by name... } }
output  { value: <JSON>, error?: { type, message } }
```

**`kind = llm`**

```
input   { model, messages[], system?, tools?, tool_choice?, response_format?,
          params { temperature, top_p, max_tokens, seed, stop } }
output  { content[] (text | tool_call | reasoning | refusal blocks),
          finish_reason,
          usage { input, output, cached, reasoning },
          model, response_id, deployment_id?,
          raw (the full provider response, JSON),
          error? }
```

`usage` is part of **output**: it is returned by the provider as part of the response.

**What goes where (the rule).** This resolves the model/provider overlap:

| Where | What | Example |
|---|---|---|
| **Input** | Passed by the caller on this call | Requested model or alias, temperature, messages, tools |
| **Output** | Known only from the response | Served model version, provider or deployment id, response id, usage |
| **Metadata** | Constant setup in code, not in the call arguments | Client library and version, `base_url`, gateway, defaults baked into the client config |

Example with a LiteLLM Router. The requested alias and the served deployment differ because of load balancing and
fallbacks (the router exposes the serving deployment on the response):

```
input.model      "gpt-4o"                        (the alias the caller asked for)
output.model     "azure/gpt-4o-2024-08-06"       (what served it)
output.deployment_id  "<router deployment id>"
metadata.gateway "litellm"
```

Pricing consumers (TokenOps) read the **served** model from output.

### 2.4 Lifecycle: one record, mutable until closed

An envelope is a **single record that is mutable until it is closed**.

- At **open**, identity and input are written; `state = open`.
- At **close**, output and `envelope_status` are written; `state = closed`. A closed envelope is immutable.
- In storage there is one record per envelope. On the wire there can be an open write and a close write.
- **`emit_open` is opt-in.** By default only the close write is sent (one write per envelope). Anything that needs the
  input before the call completes (for example intent capture) enables `emit_open`.
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
  "envelope_status": {"state": "closed", "outcome": "error",
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
  "envelope_status": {"state": "closed", "outcome": "success",
                      "started_at": "2026-10-02T10:00:02Z", "ended_at": "2026-10-02T10:00:04Z"},
  "input":  {"model": "gpt-4o", "messages": [{"role": "user", "content": "..."}]},
  "output": {"content": [{"type": "text", "text": "..."}], "finish_reason": "stop",
             "usage": {"input": 812, "output": 96, "cached": 0, "reasoning": 0},
             "model": "gpt-4o-2024-08-06", "response_id": "chatcmpl-9x..."}
}
```

### 2.6 Trace metadata

Trace-level labels live **once on the Trace**, not copied onto every envelope.
**Today** they are copied onto every envelope's `attributes`, and the labels are recovered by intersecting all envelopes
(`ExecutionGraph.attributes`); the Trace entity removes that workaround.

Chat-style applications often need `session_id`, `message_id` and `user_id`. These are **well-known Trace metadata keys**:
documented, first-class for users, but not core fields. Labels are write-once.

### 2.7 What is not a persisted entity

`ReplayPlan`, the recording session, the call log, captured inputs and results, and every view (graph, waterfall,
summaries). These are logical objects created inside a workflow, or views owned by the control plane. A "fixture" is not
an entity either: it was a trace exported to a directory, and fixtures in code are removed.

### 2.8 Versioning and the primitives repo

**Repo.** `theagentplane/primitives`. PyPI `agentplane-primitives`. Import `agentplane_primitives`. Contents: the
models above, id generation and validation, the `traceparent` carrier (parse and format), the API request and response
models, and JSON Schema export (committed, with a CI drift check). Dependencies: pydantic only. No I/O. Python 3.10+.

**Two versions.**

- The package follows SemVer.
- Every payload carries `schema_version` (`major.minor`). The package major equals the schema major.

**Rules.**

- **Additive-only within a major.** New optional fields and new kinds are allowed. Readers ignore unknown fields and
  preserve unknown kinds.
- **Breaking change = new major.** The control plane accepts the current and the previous major and upconverts on read.
- **Release order for a breaking change:** primitives, then control plane (reads both), then Chronicle and TokenOps
  (emit the new one).
- **Pre-1.0:** consumers pin the exact minor. From 1.0: `>=1.2,<2`.
- **Safety net:** a golden corpus of payloads lives in the primitives repo; every repo's CI validates against it.

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
(idempotent create; client-supplied id; labels write-once; a repeat call returns the existing trace).

- Only the first service on the path pays; downstream services that receive a `traceparent` join an existing trace.
- **Failure policy:** if the control plane is unreachable, a config flag decides: default **fail-open** (continue with the
  locally minted id and let the control plane create the trace on first ingest) or **strict** (fail the request).
- **Switchable later:** a config setting `trace_registration: sync | lazy`, so a move to lazy needs no API change.
- **Measure first:** p50 and p99 latency added at the trace root, with the control plane local and remote. The result
  decides the follow-up.
- Span registration is asynchronous: a span's existence is implied by its first envelope.

### 3.4 Events

Queues and webhooks are **Future scope**. The carrier reserves `to_event` and `from_event` names (a CloudEvents-style
tracing extension is the likely shape), documented but unimplemented.

---

## 4. Framework (in-process machinery)

### 4.1 Boundary and the interceptor

A boundary is declared with `@boundary(name, kind=...)`, `wrap(client)`, `wrap_llm(name, fn)` or the LangGraph
instrumenters. All of them go through **one interceptor** that owns the crossing lifecycle (record, stub, run).

**Today** the lifecycle is copy-pasted about six times (boundary sync and async, record and cut-point, and `wrap` sync and
async). `wrap` also skips the pre-call hook and failure capture, and reads the session's private replay cursor. The
design has a single lifecycle used by every entry point, so `wrap` gains hooks and failure capture. That is a behaviour
change to call out in the migration note.

### 4.2 Kind registry

`kind` is an open string in the schema, but behaviour per kind lives in one **strategy** per kind instead of `if` chains:
how to capture input, how to build output, how to build the stub return value, and which metadata to attach.
Registered kinds: `llm` and `tool`. An unregistered kind gets generic (tool-like) behaviour. A new kind is one strategy
and one registration.

### 4.3 Provider and tool adapters

Adapters translate between an external shape and the canonical shape.

| Direction | Status |
|---|---|
| Provider response to canonical LLM output (text, tool calls, usage, served model) | **Exists** for OpenAI-style and Anthropic-style clients (`wrap.py`, `genai.py`, `usage_from`) |
| Per-boundary shaping of input, result and metadata | **Exists** as hooks (`extract_input`, `extract_result`, `extract_metadata`) |
| Canonical back to the original return value, for replay | **Does not exist**; fixed per-kind rules today |

**Design.** An adapter is a pair keyed by provider or tool: `to_canonical(raw)` and `from_canonical(envelope)`. Today's
defaults become the first adapters. **For this sprint only the JSON path is in scope** (see 7.3). Custom adapters are a
later extension built on the same pair.

### 4.4 Hooks

**One kind of hook.** A hook is a callback with these events: `enter` (before the call; may patch keyword arguments or
abort), `leave` (after, always, if `enter` succeeded), `crossing` (the call returned and was captured), `record` (the
envelope was written).

- **Ordering:** registration order. Patches returned from `enter` are merged in order; the later one wins.
- **Failure handling:** a global config flag decides whether a hook failure fails the call
  (`hooks.fail_call_on_error`, default **false**: log and continue).
- **Deliberate abort:** a dedicated `AbortCall` exception **always propagates**, regardless of the flag. This is how a
  governor (TokenOps) stops a call on purpose. Without it, "swallow failures" would silently disable governance.
- **After the function ran:** if the flag is true, an exception from `crossing`, `record` or `leave` fails the call even
  though the function already completed; that is why the default is false.
- Hooks are registered on a session or as defaults inherited by every new session. This replaces the practice of patching
  `reset_session` to re-attach callbacks.
- **Today** there are four single-slot callbacks on the session with no ordering, and exceptions from the post-call ones
  propagate after the function ran.
- **Security surface: Future scope.** Hooks currently see raw input before redaction and the live result object, and can
  change arguments. What hooks may see and do needs its own review.

### 4.5 Redaction

Prompts and responses are production data, and secrets must not leave the process, so redaction is applied **before
anything is sent**. It is a recorder step, not a general processing framework (other in-flight transforms such as
sampling or enrichment are not in scope).

- **Provided by:** the `redactors` config setting or `record(redactors=[...])`. A redactor is `str -> str`.
- **Default:** none (opt-in). `default_redactors()` is a helper that masks common secret shapes (API keys, tokens, JWTs,
  private keys).
- **Applied to:** every string value in input, output and status messages. Keys are left alone so structure stays intact.
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

- `append` is a **non-blocking enqueue** with background batched flush. Flush also happens at span end and at shutdown.
  Batching is an internal detail of the client, not part of the contract.
- **Delivery policy** is explicit config: queue size, overflow behaviour (drop or block), timeout, and fail-open versus
  strict. Because there is no local buffer on disk, a crash can lose queued items.

### 5.2 Read side

Only replay reads from Chronicle: **the envelopes of span S in trace T.** Whole-trace reads, envelope lookups and trace
listing are control-plane concerns and are not part of Chronicle's contract.

### 5.3 What this removes

The `open_store` target registry, the JSONL and SQLite stores, the buffered-store target syntax, `read_all`, and the
local reference server. **Today** the `Store` protocol requires `read_all` and `find_by_envelope_id`, which the remote
store cannot honour (it returns empty results that look like "no data"); the narrower contract removes that mismatch.

### 5.4 Test strategy

Chronicle's own tests use an **in-memory fake** of the repository, kept inside the test suite and not shipped as a
backend. Contract tests against the primitives golden corpus cover the wire format.

### 5.5 Consequences accepted

- Replay needs a reachable control plane and a trace still within the control plane's retention.
- The zero-config local quickstart goes away; a control plane is required.
- The README's "commit the incident as a fixture" story changes to "replay a recorded trace by id".
- Chronicle's existing tests and examples that use fixtures, JSONL or the local server need rewriting.

---

## 6. Capability: Record

### 6.1 Workflow (one request)

1. **Entry.** An inbound request is intercepted by a framework instrumenter or the custom API (section 8.2).
   - A valid `traceparent` is present: **join** that trace, open a Span with `parent_envelope_id` set from it.
   - Otherwise **mint** a `trace_id`, register it synchronously (3.3), open the first Span.
2. **Per crossing** (inside the Span):
   1. Capture input. If `emit_open` is on, send the open write now.
   2. Run `enter` hooks (may patch arguments or abort).
   3. Call the wrapped function (sync or async).
   4. Build output (via the kind and adapter). On exception, record `outcome = error` with error details in output and
      re-raise.
   5. Apply redaction.
   6. Close the envelope and enqueue the write.
   7. Run `crossing`, `record` and `leave` hooks.
3. **Outbound call to another service.** The outbound HTTP client is itself a tool boundary. Its envelope id is injected as
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
  the test can assert on them. The cursor advances even if the call raises.
- A cut-point is a REPLAY session with at least one boundary on `RUN`.
- A **replay plan** (which boundary and which invocation is `STUB` or `RUN`) is a logical object, not an entity.

### 7.3 Stub internals and fidelity

For a stubbed call, Chronicle takes the next recorded envelope for that boundary name (cursor), then rebuilds the return
value from the recorded output.

**Fidelity rule for this sprint: JSON outputs only.** The full return must be JSON-serializable (dict, pydantic model,
dataclass). Replay hands back that JSON wrapped in a dict-like proxy so attribute access works.

**What was wrong today** (so the design does not repeat it):

- `@boundary(kind="llm")` and `wrap_llm` only understand a dict with keys `completion`, `tool_calls`, `finish_reason`
  and `usage`. An SDK-object return is stored as its repr string, and replay then returns a state dict with
  `completion = None`. Extra keys in a dict return are dropped, and input arguments are echoed into the stub return.
- `wrap(client)` stores the complete response but replays it through a lookalike object.
- Tools store `str(result)` for anything non-JSON.

The requirement is to store the full return in lossless JSON (`raw`) and rebuild from it. Rebuilding the original Python
type is a later adapter feature (4.3).

### 7.4 Limitations (stated up front)

- **Matching is by name plus call count, not by input.** If a fix calls a tool with different arguments or in a different
  order, replay still returns the n-th recording of that tool.
- **Async tool calls.** Even with deterministic code, the order in which parallel calls start can change, so the call
  number can change, and the wrong recording can be served.
- **Non-JSON returns are not supported** (7.3).

### 7.5 Verification

The main flow is the supported one: replay your agent with boundaries intercepted, then assert on what the live code
returned (`captured_input` and `captured_result` for the `RUN` boundaries).

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
| ASGI middleware (FastAPI, Starlette, any ASGI app) | yes | |
| Custom API: `chronicle.extract(headers)` plus `chronicle.span(parent=...)` for any other entry point (CLI jobs, workers) | yes | |
| WSGI (Flask, Django), AWS Lambda, gRPC server, A2A servers, MCP servers | | yes |

MCP over stdio has no headers; the later design uses the JSON-RPC `_meta` field.

### 8.3 Output integration (calls leaving the service)

| Mechanism | v1 | Later |
|---|---|---|
| `httpx` instrumenter: records the call as a tool envelope and injects its id as the `traceparent` parent | yes | |
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
| | `inject_hosts` | Allow-list; default deny |
| Hooks | `hooks.fail_call_on_error` | Whether a hook failure fails the call (default false). `AbortCall` always propagates. |
| Delivery | `batch_size`, `flush_interval`, `max_queue` | Buffering |
| | `on_overflow` | `drop` or `block` |
| | `timeout`, `fail_open` | Network behaviour |
| Trace registration | `trace_registration` | `sync` (now) or `lazy` (later) |
| | `registration_fail_open` | Behaviour when the control plane is unreachable |
| Intent capture | `emit_open` | Send an open write for each envelope (default off) |

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
5. Committed JSON Schema with a drift check; golden payload corpus; versioning policy from 2.8.

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

1. Remove `delegate` from `NodeType` (now `llm | tool`); delegates become ordinary tool observations. Drop the
   `rolled_up_cost_micros` handling and the delegate branch in `ledger.py`. Spend is already booked once, in the child's
   LLM calls, so totals are unaffected.
2. Replace `X-TokenOps-Run-Id` and `X-TokenOps-Parent-Span-Id` with Chronicle's `traceparent`. How `run_id` relates to
   `trace_id` (equal, or a Trace label) is still to be decided.
3. Read usage from the envelope's output (`input`, `output`, `cached`, `reasoning`) and the served model, rather than from
   the live result object.
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
| 5 | Single record, mutable until closed; `emit_open` opt-in; no `unfinished` state yet. | Supports intent capture without doubling default traffic; the crash gap is accepted. |
| 6 | One kind of hook; global fail-call flag; `AbortCall` always propagates. | Keeps hooks simple while letting a governor stop a call deliberately. |
| 7 | v1 instrumenters: ASGI, `httpx`, custom API; allow-list default deny. | Minimum for the three repos; avoids leaking trace ids to third parties. |
| 8 | Remote-only; tests use an in-memory fake. | One backend; the control plane owns storage. Consequences listed in 5.5. |
| 9 | `theagentplane/primitives` and the versioning plan in 2.8. | The control plane owns the schema; Chronicle must not depend on server code. |
| 10 | JSON outputs only for stub fidelity; per-provider and per-tool adapters considered. | Rebuilding Python types is later work. |
| 11 | Replay scoped to `trace_id` plus `span_id`; name-plus-count matching with documented limitations. | A span is the service request instance; matching improvements are future work. |
| 12 | Kinds: `llm` and `tool` only. Delegate is a tool. | A router is an LLM call or a function; the delegate link is carried by `traceparent`. |
| 13 | Config surface in section 9. | One documented place for everything Chronicle honors. |
| 14 | Clean break from 0.5.0 (schema, remote-only, removals). | The change cannot be additive. |
| 15 | Order of work: primitives, control plane, Chronicle and TokenOps. | Each depends on the schema above it. |
| 16 | Chronicle does not change for TokenOps now; in-flight counting stays in TokenOps. | It counts concurrent LLM calls and does not depend on `delegate`. |
| 17 | Visualization, OTel export and export features belong to the control plane. | Chronicle is an edge component (P2). |
| 18 | Streaming, events, fan-in, TestCase, Layer 2, `unfinished` state: Future scope. | Not needed this sprint. |

---

## 12. Limitations, future scope and migration

### 12.1 Future scope

- **Events** (queues, webhooks) and the event carrier.
- **Streaming** capture and replay (6.5).
- **Fan-in** links.
- **TestCase** entity and a pytest runner.
- **Layer 2** LLM-as-judge and assertion helpers.
- **`unfinished` state** with a timeout, and span-derived concurrency counting.
- **Adapters** that rebuild original Python types on replay (4.3).
- **Hook security review**: what hooks may see and do (4.4).
- **More instrumenters** (8.2, 8.3).
- **Better replay matching** (by input fingerprint) to address async reordering (7.4).
- **Lazy trace registration** after the latency measurement (3.3).

### 12.2 Open items

- **Version number** of the clean break: 0.6 or 1.0.
- **`run_id` and `trace_id`** relationship for TokenOps (10.3).
- **Decoupling hooks from `enabled`** (section 9): proposed, not yet confirmed.
- **Adding hooks that need sync registration for spans** if TokenOps requires it: spans are async for now.

### 12.3 Migration from 0.5.0

A clean break with one migration note:

- Envelope shape changes (flat to sections; `attributes` to `metadata`); `router` and `custom` kinds become `tool`.
- Local stores, fixtures, the CLI and the local server are removed.
- `wrap` now runs hooks and records failures.
- Existing fixtures under `fixtures/` are not replayable; re-record against the control plane.
- Hooks: the single-slot callbacks are replaced by the hook contract.
