# Migrating from Chronicle 0.5 to 1.0

1.0 is a clean break (design decision 14). The change cannot be additive: the envelope shape, the
storage model and the replay unit all changed. This note lists what to do, in the order you will
hit it. Every item is also classified in the [changelog](../CHANGELOG.md).

## 1. Install

```bash
pip install "agent-chronicle>=1.0,<2"      # pulls agentplane-primitives==0.1.*
```

Chronicle now needs a **control plane** to save to and to replay from. The zero-config local
quickstart is gone.

## 2. Configure where to save

```python
chronicle.configure(
    control_plane_url="http://control-plane:8000", api_key="...", service_name="my-agent"
)
# or CHRONICLE_CONTROL_PLANE_URL, CHRONICLE_API_KEY, CHRONICLE_SERVICE_NAME
```

| 0.5 | 1.0 |
|---|---|
| `record(store=..., export=..., retain_envelopes=...)` | `configure(control_plane_url=...)`; no export, no local copy |
| `record(name, attributes={...})` | `record(name, labels={...})` (labels are trace-level, string values, written once) |
| `CHRONICLE_ENABLED=0` | `CHRONICLE_ENABLED=0` (recording off; **hooks keep running**) |
| `session.redactors = default_redactors()` | `configure(default_redactors=True)` |

## 3. Boundaries

- `kind` is `"llm"` or `"tool"`. Change `"router"` and `"custom"` to `"tool"`. The default kind is
  now `"tool"`.
- `@boundary`, `wrap`, `wrap_llm` keep their signatures. `wrap` now also runs hooks and records
  failures.
- For `kind="llm"` pass `provider="openai"` (or `"anthropic"`, ...) or an `adapter=` when you do
  not use `wrap(client)`; otherwise `usage` is `null` and `provider` is `unknown`.
- Boundary inputs and outputs must be JSON-serializable. Anything else is stored as its `repr`.

## 4. Reading envelopes

Import the models from primitives and read the sections:

| 0.5 (`chronicle.Envelope`) | 1.0 (`agentplane_primitives.models.Envelope`) |
|---|---|
| `envelope.input.arguments` | `envelope.input.raw` |
| `envelope.input.messages` | `envelope.input.messages` (LLM) |
| `envelope.output.value` | `envelope.output.raw` |
| `envelope.output.llm.text` | the `text` blocks of `envelope.output.content` |
| `envelope.output.llm.usage` | `envelope.output.usage` (exclusive, additive buckets) |
| `envelope.status.code == "ERROR"` | `envelope.envelope_status.status == "failure"`, error in `output.error` |
| `envelope.attributes[...]` | `envelope.metadata[...]`; trace labels are on the `Trace` |
| `envelope.sequence`, `invocation_index` | `metadata["chronicle.sequence"]`, `metadata["chronicle.invocation_index"]` |
| `envelope.start_time`, `end_time` | `envelope_status.started_at`, `ended_at` |

Usage buckets changed meaning: OpenAI counts cached tokens inside the prompt total, so `input` is now
the **non-cached** part and `cached_read` is separate. The sum of the buckets is the provider's total.

## 5. Hooks

```python
# 0.5
session.on_enter = lambda name, kind, input: ...


# 1.0
class Governor(chronicle.Hook):
    def enter(self, call): ...  # may return kwargs to merge, or raise AbortCall


chronicle.default_hooks.register(Governor())
```

Events are `enter`, `leave`, `crossing` and `record`, run in registration order. Raise
`chronicle.AbortCall` to stop a call on purpose; it always propagates. Stop patching
`reset_session`: register as a default hook instead.

## 6. Replay

```python
# 0.5: from a fixture directory
chronicle.replay_trace(
    "fixtures/traces/incident-001/", ReplayPlan().stub("agent", 1).live("delete_file", 1)
)
# 1.0: from the control plane, by span
chronicle.replay_trace(trace_id, span_id, ReplayPlan().run("delete_file", 1))
```

- `.live(...)` is `.run(...)`; modes are `STUB` and `RUN`.
- A STUB returns the recorded `output.raw` (JSON with attribute access), not a rebuilt dict. A recorded
  failure is re-raised as `RecordedCallError`.
- **Old fixtures are not replayable.** Re-record the incident against the control plane.
- `ReplayInjector`, `StructuralAssertions` and `ExecutionGraph` are removed. Assert on
  `run.captured_input(name, n)` and `run.captured_result(name, n)` instead.

## 7. Cross-service traces

Add the middleware to every service and turn the instrumenter on once; list the peers:

```python
app.add_middleware(chronicle.ChronicleMiddleware, service="orchestrator")
chronicle.configure(inject_hosts=["specialist.internal"])
chronicle.instrument_httpx()
```

Injection is **default deny**: a peer not in `inject_hosts` does not get the header and starts its
own trace.

## 8. Removed

The CLI, `visualizer`, `instrument_otel` and `envelope_span_attributes`, Phoenix and OpenInference
instrumentation, the JSONL, SQLite and remote stores (`open_store`, `BufferedStore`), the local
reference control plane and committed fixtures. Visualization and OpenTelemetry export are the
control plane's job.

The old examples are parked in `_legacy_demos/` and do not run yet.
