# Roadmap

Chronicle is at 1.0: the API, the configuration and the wire behaviour are stable within a major
version (see [docs/versioning.md](docs/versioning.md)); new work is additive. Nothing here is a dated commitment. The design's list of what is
deliberately not built yet is
[section 12.1 of the technical design](docs/rfcs/chronicle-technical-design.md); priorities are shaped
in [Discussions](https://github.com/theagentplane/chronicle/discussions) and tracked in
[issues](https://github.com/theagentplane/chronicle/issues).

## Near-term

### Streaming capture and replay
Close the envelope when the stream ends, accumulate chunks into the canonical output, record time to
first token and cancellation as partial output, and re-emit a recording as a stream on replay.
Today `stream=True` passes through unrecorded.

### More adapters
OpenAI Responses API (issue #61), Azure OpenAI deployment names, Gemini, Bedrock Converse (which
returns no served model). Tool adapters for HTTP, MCP and A2A calls.

### Local control-plane scaffold and the demos
A scaffold that starts a local control plane (replacing the zero-config quickstart that 1.0
removes), and the examples, demo and scripts in `_legacy_demos/` rewritten to run against it.

## Later

- **Serialization hardening:** type-tagged values, a visible loss marker and a strict mode for
  anything that cannot be converted to JSON.
- **Rebuilding original Python types** from `raw` on replay.
- **Better replay matching** by input fingerprint, to address reordering of parallel calls.
- **A pytest runner and `TestCase`**, assertion helpers (tools called, argument keys, finish
  reason) and the LLM-as-judge layer.
- **`unfinished` state** with a timeout, and fan-in links.
- **Events:** queues and webhooks, with the `to_event` and `from_event` carrier.
- **Trace-context trust:** tenant-scoped trace keys and optional signed context.
- **Hook security review:** what hooks may see and do.
- **More instrumenters:** WSGI, `requests`, `aiohttp`, gRPC, MCP.
- **Lazy trace registration**, once the latency at the trace root has been measured.

## Recently shipped

See [CHANGELOG.md](CHANGELOG.md). 1.0.0 is a rebuild on `agentplane-primitives` with a remote-only
repository client, an interceptor shared by every entry point, provider conformance tests and an
end-to-end suite of multi-agent systems over A2A and HTTP.

---

Have an idea or a priority? Open a
[Discussion](https://github.com/theagentplane/chronicle/discussions) or an
[issue](https://github.com/theagentplane/chronicle/issues).
