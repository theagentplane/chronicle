# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **`CHRONICLE_ENABLED`**: set to `0` / `false` / `off` / `no` to turn off LIVE
  recording. `@boundary`, `wrap`, `wrap_llm`, `record()`, and `EnvelopeRecorder`
  become passthrough so an agent can be run with and without Chronicle. Replay is
  unaffected. Check with `chronicle.is_enabled()`.
- **`BufferedStore`**: in-memory buffer with batched flush over any inner store
  (`JsonlStore.append_many` for one open/write). Also
  `open_store("buffered:32:runs.jsonl")`.

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

[Unreleased]: https://github.com/theagentplane/chronicle/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/theagentplane/chronicle/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/theagentplane/chronicle/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/theagentplane/chronicle/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/theagentplane/chronicle/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/theagentplane/chronicle/releases/tag/v0.1.0
