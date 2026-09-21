# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed (breaking)
- **No tool-schema capture.** `ToolSchema`, `Envelope.tool_schemas`, `gen_ai.tool.*` / `gen_ai.operation.name` attributes and the GenAI *execute tool* span convention are not part of this release: tool definitions are not recorded, and a `kind="tool"` boundary records only `chronicle.input.schema` / `chronicle.output.schema` like any other method boundary. `LLMRequest` carries the model and sampling only.
- **`boundary_id` is now `name`.** The boundary's name is one concept, matching `Envelope.name`: `@boundary(name, ...)`, `wrap_llm(name, ...)`, `ReplayPlan.stub/live/mode_for/should_stub(name, ...)`, `ChronicleSession` methods and `CallRecord.name`. The `Envelope.boundary_id` getter is removed; use `Envelope.name`. Positional calls and the `on_enter` / `on_leave` / `on_crossing` hooks (called positionally) are unaffected; keyword uses of `boundary_id=` and reads of `.boundary_id` must change.
- **Removed `EnvelopeRecorder`** (`chronicle/envelope/capture.py`), `instrument_graph_nodes` and the LangGraph extractors (`chronicle/instrumentation/langgraph.py`), and `examples/langgraph_demo/agent.py`. Use `chronicle.record()`, `@boundary` and `chronicle.instrument_langgraph(nodes)`. `chronicle init` now points there too.
- **OpenTelemetry-format ids.** `trace_id` is now an OTel trace id (32 lowercase hex
  chars, 16 bytes) and `envelope_id` / `parent_envelope_id` are OTel span ids (16
  lowercase hex chars, 8 bytes). They are validated on `Envelope`, generated from random
  bytes, and no longer free-form strings. Envelopes with UUID or free-form ids (fixtures
  recorded before this release) no longer load: re-record them.
- **`record(name=...)` / `begin_trace(name=...)`.** The first argument is now a human
  label, stored as the `chronicle.trace.name` attribute on every envelope. `trace_id=` is
  keyword-only and accepts only an OTel trace id. Calls like `record("incident-001")`
  keep working, but the label is no longer the trace id.
- **Exported OTel spans reuse the envelope's ids** (trace id, span id, parent) and its
  start/end times, so a platform sees the same ids Chronicle recorded. The
  `chronicle.envelope_id` / `chronicle.trace_id` span attributes are gone (redundant).
- **Span ids are unique per trace, not globally.** `find_by_envelope_id(envelope_id,
  trace_id=None)` takes an optional `trace_id`; `SqliteStore` keys rows on
  `(trace_id, envelope_id)` (new databases only); the control-plane RFC keys on the pair.
- `EnvelopeStore.export_trace` writes `NNN-<boundary>-<invocation>.json` (same as
  `ExecutionGraph.save`) instead of prefixing the trace id.
- Fixtures are re-recorded from real runs (`fixtures/`). The deletion, refund, invoice
  and trade traces come from `examples/`; `examples/nested_subagents/record.py` and
  `examples/sample_envelope/record_sample.py` replace the hand-written nested-trace and
  single-envelope samples (now `fixtures/envelopes/support-agent-001.json`). Sequential
  top-level boundaries are sibling roots (nest-stack parenting), not a linear chain.

- **Envelope fields use OTel span names** (`schema_version` is now `2.0`; older envelopes
  no longer load, so re-record them):

  | Before | Now |
  |---|---|
  | `node_id` | `name` (the boundary name) |
  | `boundary_kind` | `kind` (`llm` / `tool` / `router` / `custom`) |
  | `started_at` | `start_time` |
  | `timestamp` | `end_time` |
  | `dims` (and `record(dims=...)`, `session.dims`, `ExecutionGraph.dims`) | `attributes` |
  | `action_result.error` / `error_type` | `status` (`code` `UNSET`/`OK`/`ERROR` + `message`) and the `error.type` attribute |

  The `boundary_kind` / `node_id` stamps are no longer copied into `attributes` (they are
  fields now), and exported OTel spans carry envelope attributes under their own keys
  instead of `chronicle.dims.<key>`. `graph.json` span entries use `name` / `kind`, and
  its top-level `dims` is now `attributes`. The failure status message is redacted like
  the rest of the envelope. The `@boundary(kind=...)` argument is unchanged.

- **`Envelope.metadata` is gone.** The model and sampling parameters are
  span attributes under the OTel GenAI keys (`gen_ai.request.model`,
  `gen_ai.request.temperature` / `top_p` / `max_tokens` / `seed`),
  so a backend sees them natively. `Envelope.model` reads the model
  back. `attributes` values are now OTel-typed (`str`, `bool`, `int`, `float` or lists of
  them), not only strings. `build_id`, `framework`, `extra` and `SamplingParams.extra` are
  removed (with `record(build_id=)`, `session.build_id`, `CHRONICLE_BUILD_ID`, and the
  `chronicle.build_id` span attribute). `record(model_version=)` is now `record(model=)`.
- **`InputState` → `Input`** (`Envelope.input_state` → `Envelope.input`) with a minimal shape:
  `arguments` (the call's arguments by name; replaces `graph_state`) and `messages` (typed
  `Message`s, LLM boundaries only). `system_prompt`, `rag_chunks` and `content_hash` are no
  longer fields (a `rag_chunks` argument stays in `input.arguments`), and `RagChunk` / `rag_chunks_from` are removed.
- **`ActionResult` → `Output`** (`Envelope.action_result` → `Envelope.output`):
  `value` (the JSON-safe return value; replaces `raw_response`) and `llm`, one `LLMOutput`
  bundle (`text`, `tool_calls`, `finish_reason`, `usage`) for LLM boundaries. `usage` is a
  normalized `Usage(input_tokens, output_tokens)` instead of a provider-keyed dict.

- **OTel dependencies** in the `[otel]` extra are bumped to the latest releases:
  `opentelemetry-api` / `-sdk` / `-exporter-otlp` >= 1.44, `openinference-instrumentation` >=
  0.1.65, `openinference-semantic-conventions` >= 0.1.38, and `opentelemetry-semantic-conventions`
  >= 0.65b0 is now listed explicitly (the GenAI keys are tested against it).

### Added
- **Method boundaries record their shape, inferred from the wrapped method.** Every
  non-LLM boundary stores `chronicle.input.schema` (JSON schema of the signature; an
  unannotated method still records its parameter names) and `chronicle.output.schema` (the
  return annotation, when there is one), readable as `Envelope.input_schema` /
  `Envelope.output_schema`.
- `chronicle.LLMRequest`, a validated capture-side view (model, sampling) that
  flattens into attributes with `to_attributes()`; `Envelope.model`.
- `chronicle.Status` and `Envelope.status`; `span_id` and
  `parent_span_id` remain as getters.
- `chronicle.ids`: `new_trace_id`, `new_span_id`, `is_trace_id`, `is_span_id`.
- **`chronicle.instrument(graph)`**: one call auto-instruments every node *and*
  every `add_conditional_edges` routing function on a LangGraph `StateGraph`,
  before or after `.compile()`. Routing decisions are now recorded as
  `kind="router"` boundaries and replay deterministically (which branch was
  taken), not just each node's input/output. (#22)

## [0.4.0] - 2026-08-14

### Changed
- **`RemoteStore`** now talks to the AgentPlane control plane: `POST /v1/envelopes:batch`
  for writes and `GET /v1/traces/{trace_id}/envelopes` for replay. Failed remote
  writes warn and drop rather than crashing the agent.

### Added
- **Trace/envelope `dims`**: flat `dict[str, str]` attributes on every envelope.
  Pass trace-level dims via `chronicle.record(..., dims={...})`; they are copied
  onto each span. Envelope-specific dims (e.g. `model_version`) merge on top.
  File storage only for now (JSONL / fixture export). Lookup by dims belongs on
  the shared control plane / dashboard, not in this library.
- **OTel-style nest parents**: boundaries open a span on the Context stack before
  the body runs (`start_span` / `end_span`), so nested calls set
  `parent_envelope_id` to the active parent (not the last finished envelope).
  Optional debug helpers: `ExecutionGraph.to_otel_tree()` /
  `to_otel_waterfall()` (product UI stays shared with TokenOps / the plane).
- **Dev / CI extras**: `[dev]` installs `[otel]` (OpenTelemetry + OpenInference)
  instead of full `[phoenix]`, so `arize-phoenix` is not pulled into pytest
  collection (its pytest plugin has been crashing CI on Python 3.11). Use
  `pip install agent-chronicle[phoenix]` when you want the Phoenix collector/UI.
- **`CHRONICLE_ENABLED`**: set to `0` / `false` / `off` / `no` to turn off LIVE
  recording. `@boundary`, `wrap`, `wrap_llm`, `record()`, and `EnvelopeRecorder`
  become passthrough so an agent can be run with and without Chronicle. Replay is
  unaffected. Check with `chronicle.is_enabled()`.
- **`BufferedStore`**: in-memory buffer with batched flush over any inner store
  (`JsonlStore.append_many` for one open/write). Also
  `open_store("buffered:32:runs.jsonl")`.
- **Recording hot-path speedups**: cache `inspect.signature` per boundary,
  dataclass-aware `_json_safe`, `Envelope.model_construct` on LIVE record,
  `JsonlStore(keep_open=True)`, and `retain_envelopes=` on `record()` /
  session (skip in-memory list when only the store write is needed).
- **BufferedStore durability**: `record()` flushes the store on context exit;
  failed flushes restore the in-memory batch instead of dropping it.
- **Message capture**: `_json_safe` keeps full dataclass / duck-typed message
  fields (not just `role`/`content`); every messages entry is coerced to a dict.

## [0.3.0] - 2026-07-24

### Added
- **`session.on_enter` / `session.on_leave`**: pre-call and paired cleanup hooks on
  `@boundary` / `wrap_llm` (LIVE + live cut-point). `on_enter` runs after input
  capture and before the wrapped function; it may raise to abort the call, or
  return a kwargs mapping to merge (MUTATE). `on_leave` runs after the attempt
  when `on_enter` completed, including when the function raises. Governors
  (e.g. TokenOps) use this for LLM-kind pre_call without a separate wrap.

## [0.2.0] - 2026-07-23

### Changed
- `@boundary` is now **transparent**: it never changes what the wrapped function
  returns or raises. `extract_result` feeds the envelope only; the caller and
  `on_crossing` always receive the real value. (Fixes a latent bug where the hook
  silently replaced the return value.)
- **Zero-config capture** now binds the real signature and records arguments by
  their real names (skipping `self`), instead of shape-sniffing. `wrap_llm` no
  longer needs a special extractor. Note: the recorded `graph_state` shape changes
  for some call patterns, so fixtures recorded before 0.2 may need re-recording.

### Added
- **`chronicle.wrap(client)`**: record every model call an OpenAI/Anthropic-style
  client makes, with no decorators; in replay it returns the recorded response
  (attribute/index access) and makes no API call.
- **`chronicle.instrument_langgraph(nodes)`**: wrap every LangGraph node as a
  `@boundary` in one call (record / stub-replay / cut-point; async supported).
- **Async support**: `async def` boundaries record, stub on replay, and run live at
  a cut-point exactly like sync ones (via `@boundary` and `wrap_llm`); LangGraph
  `EnvelopeRecorder.wrap_node` gains the same async path.
- **Per-request isolation**: the session is context-scoped (`ContextVar`), so
  concurrent async requests no longer share a trace.
- **Failure capture**: a boundary that raises records an envelope with the new
  `ActionResult.error` / `error_type` fields (and `finish_reason="error"`), then
  re-raises. Optional fields, so pre-0.2 envelopes load unchanged.

## [0.1.3] - 2026-07-23

### Added
- `chronicle.wrap_llm(boundary_id, dispatch, ...)`: wrap an LLM callable with the
  same LIVE / stub / cut-point + `on_crossing` contract as `@boundary(..., kind="llm")`,
  so governors (e.g. TokenOps) can subscribe without a parallel tracer.

## [0.1.2] - 2026-07-23

### Added
- `chronicle.record()` and `chronicle.replay_trace()` context managers that
  collapse session setup (reset, attach store, begin or load trace, enable
  replay) into a single `with` block. No behavior change; the same
  `ChronicleSession` is yielded for finer control.

## [0.1.1] - 2026-07-22

### Fixed
- `chronicle --version` crashed on the installed CLI with `'chronicle' is not
  installed`, because the version was resolved by import name rather than the
  `agent-chronicle` distribution. It is now passed explicitly, so it works in
  source, editable, and wheel installs.

## [0.1.0] - 2026-07-22

### Added
- `@boundary` decorator: record in live mode, stub in replay mode, run live at a
  cut-point. One annotation, three behaviors.
- Immutable, append-only Envelope capturing contextual metadata, input state,
  action/result, and graph linkage.
- Real model-version and sampling-parameter capture on the `@boundary` path, plus
  an `extract_metadata` hook for explicit overrides.
- `EnvelopeStore` (JSONL) and a side execution graph builder.
- Verification Test Bench: Layer 1 structural replay (never calls the LLM) and
  Layer 2 LLM-as-judge evaluation.
- Cut-point replay via `ReplayPlan` (stub upstream, run target live, observe
  downstream).
- Secret redaction: opt-in `session.redactors` / `default_redactors()` that mask
  API keys, tokens, and JWTs before an envelope is stored or committed.
- Trace visualizer (`chronicle show-graph --ui / --html`).
- CLI: `record`, `extract`, `replay`, `verify`, `show-graph`, `schema`,
  `list-fixtures`.
- OpenInference / Arize Phoenix normalization and optional LangGraph node
  wrapping.

[Unreleased]: https://github.com/theagentplane/chronicle/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/theagentplane/chronicle/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/theagentplane/chronicle/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/theagentplane/chronicle/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/theagentplane/chronicle/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/theagentplane/chronicle/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/theagentplane/chronicle/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/theagentplane/chronicle/releases/tag/v0.1.0
