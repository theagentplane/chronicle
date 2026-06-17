# Chronicle

Chronicle captures the execution DNA of your agents. It records granular decision states—including model versions, retrieval snapshots, tool schemas, and environment context—enabling accurate traces that allow you to navigate your agentic terrain with absolute observability.

## Architecture

Chronicle implements two complementary systems:

### 1. Agent Data Recorder ("The Envelope")

Captures "flight data" at the **graph boundary** (LangGraph nodes), not at network sockets.

Every execution serializes an immutable, append-only **Envelope**:

| Field | Contents |
|---|---|
| **Contextual Metadata** | Pinned model version, sampling parameters, runtime build ID |
| **Input State** | Full assembled prompt and retrieved context/chunks |
| **Action/Result** | Structured tool calls and model completion |

OpenInference and Arize Phoenix provide framework-agnostic tracing; Chronicle normalizes spans into a regression-ready envelope format.

### 2. Verification Test Bench

| Layer | Goal | Mechanism |
|---|---|---|
| **Layer 1: Replay** | Validate control flow / logic | Static envelope fixture; structural assertions (tool called, routing) — **never calls the LLM API** |
| **Layer 2: Evaluation** | Validate generation quality | LLM-as-a-judge on meaning (grounding, safety, refusal) — not bitwise equality |

Production incident envelopes are committed under `fixtures/envelopes/` as permanent regression tests.

## Quick Start

```bash
pip install -e ".[dev]"
pytest -m layer1          # deterministic replay (no API keys needed)
chronicle replay fixtures/envelopes/incident-2026-06-17-001.json
```

### Record agent execution

```python
from chronicle import EnvelopeRecorder
from chronicle.envelope.store import EnvelopeStore
from chronicle.instrumentation import instrument_graph_nodes

recorder = EnvelopeRecorder(
    store=EnvelopeStore(".chronicle/runs/envelopes.jsonl"),
    model_version="gpt-4o-2024-08-06",  # pinned, not an alias
    build_id="deploy-abc123",
)

wrapped_nodes = instrument_graph_nodes(recorder, {"agent": agent_node})
```

### Layer 1 replay (deterministic)

```python
from chronicle.replay import ReplayInjector
from chronicle.envelope.schema import Envelope

envelope = Envelope.from_file("fixtures/envelopes/incident-2026-06-17-001.json")
injector = ReplayInjector(envelope)

def agent(state, inj):
    completion = inj.stub_llm()          # no API call
    inj.stub_tool("search_docs", {"query": "reset API key"})
    return {"finish_reason": completion.finish_reason}

_, _, assertions = injector.replay(agent)
assert all(a.passed for a in assertions)
```

### Layer 2 evaluation (LLM-as-judge)

```python
from chronicle.judge import JudgeRunner, OpenAIJudgeClient

runner = JudgeRunner(OpenAIJudgeClient(model="gpt-4o-mini"))
result = runner.evaluate(envelope)
assert result.overall_passed
```

## Workflow

```
Instrument → Capture → Extract → Debug → Fix → Verify
     │           │          │        │       │      │
     │           │          │        │       │      └─ Layer 1 + Layer 2
     │           │          │        │       └─ Modify agent logic/prompt
     │           │          │        └─ Step through frozen envelope
     │           │          └─ chronicle extract --trace-id <id>
     │           └─ EnvelopeRecorder at graph nodes
     └─ OpenInference + Phoenix bootstrap
```

## CLI

```bash
chronicle record                  # Bootstrap tracing + instrumentation
chronicle extract --trace-id ID   # Export envelopes to fixtures/
chronicle replay FIXTURE.json     # Layer 1 deterministic replay
chronicle verify FIXTURE.json --layer2  # Layer 1 + Layer 2
chronicle schema                  # Print Envelope JSON Schema
chronicle list-fixtures           # List committed regression cases
```

## Environment Variables

| Variable | Purpose |
|---|---|
| `CHRONICLE_BUILD_ID` | Pin runtime build ID in envelope metadata |
| `CHRONICLE_STORE` | Default envelope store path |
| `PHOENIX_COLLECTOR_ENDPOINT` | Phoenix OTLP endpoint (default `http://localhost:4317`) |

## Project Structure

```
chronicle/
├── envelope/          # Schema, capture, append-only store
├── instrumentation/   # OpenInference + LangGraph hooks
├── replay/            # Layer 1 injector + structural assertions
├── judge/             # Layer 2 rubric + LLM-as-judge runner
├── cli.py             # chronicle CLI
fixtures/envelopes/    # Committed regression envelopes
examples/langgraph_demo/
tests/
```

## License

MIT
