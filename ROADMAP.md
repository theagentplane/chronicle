# Roadmap

Chronicle is early (0.x). The Envelope schema may still change between minor versions,
so pin a version and re-record if you upgrade across a schema change.

This page lists what is planned and roughly in what order. Nothing here is a dated
commitment. Priorities are shaped in
[Discussions](https://github.com/theagentplane/chronicle/discussions), and the details
are tracked in [issues](https://github.com/theagentplane/chronicle/issues).

## Near-term

### Streaming and async generators
Capture streamed / server-sent responses and `async def` generators, recording the
assembled result at the boundary. Today you record the non-streamed response.

### Auto-instrument compiled LangGraph
Wrap a compiled LangGraph app in one call and capture routing and edge decisions, not
just node I/O. Today `instrument_langgraph(nodes)` wraps a node dict by hand.

### pytest integration
A thin helper so a committed incident becomes a one-decorator regression test, on top of
the existing `replay_trace(...)` context manager.

## Later

### Docs site
A browsable docs site beyond this README and the
[onboarding guide](docs/onboarding.md).

### Toward a stable 1.0
Freeze the Envelope schema and commit to backward-compatible fixtures, so a recording
made today keeps replaying across upgrades.

## Recently shipped

See [CHANGELOG.md](CHANGELOG.md) for the full history. Highlights from `0.2.0`:

- Transparent capture: `@boundary` never changes what your function returns or raises.
- `async def` boundaries with per-request session isolation.
- One-line entry points: `wrap(client)`, `wrap_llm(name, fn)`, `instrument_langgraph(nodes)`.
- Failure capture: a boundary that raises records an error Envelope and re-raises.
- Secret redaction via `default_redactors()`.

---

Have an idea or a priority? Open a
[Discussion](https://github.com/theagentplane/chronicle/discussions) or an
[issue](https://github.com/theagentplane/chronicle/issues).
