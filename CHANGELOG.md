# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/theagentplane/chronicle/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/theagentplane/chronicle/releases/tag/v0.1.0
