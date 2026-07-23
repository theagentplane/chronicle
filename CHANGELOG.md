# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.3] - 2026-07-23

### Added
- `chronicle.wrap_llm(boundary_id, dispatch, ...)` — wrap an LLM callable with the
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

[Unreleased]: https://github.com/theagentplane/chronicle/compare/v0.1.3...HEAD
[0.1.3]: https://github.com/theagentplane/chronicle/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/theagentplane/chronicle/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/theagentplane/chronicle/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/theagentplane/chronicle/releases/tag/v0.1.0
