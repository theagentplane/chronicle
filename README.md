# Chronicle

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/agent-chronicle.svg)](https://pypi.org/project/agent-chronicle/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://pypi.org/project/agent-chronicle/)
[![CI](https://github.com/theagentplane/chronicle/actions/workflows/ci.yml/badge.svg)](https://github.com/theagentplane/chronicle/actions/workflows/ci.yml)
[![Contributor Covenant](https://img.shields.io/badge/Contributor%20Covenant-2.1-4baaaa.svg)](CODE_OF_CONDUCT.md)

Chronicle captures the execution DNA of your agents through record-and-replay for agent decision graphs. It records granular decision states including model versions, retrieval snapshots, tool schemas, and environment context; enabling accurate traces that allow you to navigate your agentic terrain with absolute observability.

## Architecture

Chronicle implements two complementary systems:

### 1. Agent Data Recorder ("The Envelope")

Captures "flight data" at **decision boundaries**—the methods where your agent calls an LLM, runs a tool, or makes a routing decision. Chronicle builds a **side execution graph** alongside your agent without modifying framework topology.

Every boundary invocation serializes an immutable, append-only **Envelope**:


| Field                   | Contents                                                         |
| ----------------------- | ---------------------------------------------------------------- |
| **Contextual Metadata** | Pinned model version, sampling parameters, runtime build ID      |
| **Input State**         | Full assembled prompt, graph state, retrieved context/chunks     |
| **Action/Result**       | Structured tool calls and model completion                       |
| **Graph linkage**       | `parent_envelope_id`, `sequence`, `invocation_index` for retries |


OpenInference and Arize Phoenix provide framework-agnostic tracing; Chronicle normalizes observations into a regression-ready envelope format.

### 2. Verification Test Bench


| Layer                   | Goal                               | Mechanism                                                                           |
| ----------------------- | ---------------------------------- | ----------------------------------------------------------------------------------- |
| **Layer 1: Replay**     | Validate control flow / logic      | Static envelope/trace fixtures; structural assertions — **never calls the LLM API** |
| **Layer 2: Evaluation** | Validate generation quality        | LLM-as-a-judge on meaning (grounding, safety, refusal) — not bitwise equality       |
| **Cut-point replay**    | Test a code change in one boundary | Stub upstream from fixtures, run target boundary live                               |


Production incidents are committed under `fixtures/traces/` (multi-step graphs) or `fixtures/envelopes/` (single-step) as permanent regression tests.

## Quick Start

```bash
pip install -e ".[dev]"

# Cross-platform (Windows, macOS, Linux):
python scripts/run.py demo       # interactive demo (confirms each step)
python scripts/run.py test       # full pytest suite (separate)

# Non-interactive (CI / automation):
python scripts/run.py demo -y

# Shell wrappers (Unix):
./scripts/demo.sh
./scripts/test.sh

# Batch wrappers (Windows):
scripts\demo.bat
scripts\test.bat
```

The demo walks through record → trace → optional UI → cut-point replay, **confirming before each step**. It does not run pytest — use `test` for that.

```bash
pytest -v                 # or: python scripts/run.py test
pytest -m layer1 -v       # deterministic replay only
```

## Primary API: `@boundary`

Annotate decision boundaries once. The same annotation records in live mode and stubs in replay mode.

```python
from chronicle import boundary, get_session, reset_session, ReplayPlan
from chronicle.envelope.store import EnvelopeStore

@boundary("agent", kind="llm")
def agent_plan(state: dict) -> dict:
    ...

@boundary("delete_file", kind="tool")
def delete_file(path: str, environment: str) -> dict:
    ...

# Record mode (default)
session = reset_session()
session.store = EnvelopeStore(".chronicle/runs/incident.jsonl")
session.begin_trace("trace-001")
result = run_agent(...)

# Export trace graph to fixtures/
session.export_trace("fixtures/traces/incident-001/")
```

### Cost / governance observers (`on_crossing`)

Chronicle does **not** embed cost management. External systems (e.g. TokenOps) attach an observer:

```python
session = reset_session()
session.on_crossing = my_observer  # (boundary_id, kind, input_state, result) -> None
```

Invoked after **LIVE** envelope record and **LIVE** cut-point capture. **Not** called on STUB replay. See `tests/test_cost_management_e2e.py` for an end-to-end fake ledger/budget pattern.

### How `@boundary` wraps your function

Same decorator, two behaviors. The wrapper sits around your function — it does not replace your logic.

#### 1. LIVE mode — capture input & output

Your function **runs normally**. Chronicle snapshots what went in and what came out, then saves an **Envelope**.

```
┌────────────────── @boundary wrapper (LIVE) ────────────────────────────┐
│                                                                        │
│   @boundary("place_order", kind="tool")  ◄── annotate once             │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │  INPUT captured                                                │   │
│   │  symbol=ACME  quantity=1000  side=sell  (args → InputState)    │   │
│   └────────────────────────────────────────────────────────────────┘   │
│                              │                                         │
│                              ▼                                         │
│   def place_order(symbol: str, quantity: int) -> dict:                 │
│       notional = quantity * SHARE_PRICE                                │
│       return {"status": "filled", "notional_cents": notional}          │
│                              │                                         │
│                              ▼                                         │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │  OUTPUT captured                                               │   │
│   │  {"status": "filled", "notional_cents": 19000000, ...}         │   │
│   └────────────────────────────────────────────────────────────────┘   │
│                              │                                         │
│                              ▼                                         │
│                    Envelope → store → fixtures/traces/                 │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

#### 2. Replay / eval mode — mimic output from a saved Envelope

Your function **does not run**. Chronicle returns the **same output** that was recorded during the incident (from the fixture trace).

```
┌────────────────── @boundary wrapper (EVAL + stub) ─────────────────────┐
│                                                                        │
│   @boundary("place_order", kind="tool")  ◄── same decorator            │
│                                                                        │
│   ReplayPlan(trace_id).stub("place_order",1) ◄── eval: freeze this step│
│                                                                        │
│   def place_order(symbol: str, quantity: int) -> dict:                 │
│       notional = quantity * SHARE_PRICE                                │
│       return {"status": "filled", ...}     ◄── NOT executed            │
│                                                                        │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │  OUTPUT returned from saved Envelope (incident fixture)        │   │
│   │  {"status": "filled", "notional_cents": 19000000, ...}         │   │
│   │  mimics the output Chronicle captured in LIVE mode             │   │
│   └────────────────────────────────────────────────────────────────┘   │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

For cut-point tests, one boundary can be set to **live** instead of stub — the wrapper runs your **new** function body while upstream steps still mimic the saved Envelope. See [Cut-point replay](#cut-point-replay) below.

### Cut-point replay

Test a fix in one boundary while stubbing everything else from the incident:

```python
session = reset_session()
session.load_trace("fixtures/traces/deletion-incident-001/")
session.enable_replay(
    ReplayPlan()
    .stub("agent", 1)          # upstream: frozen from fixture
    .live("delete_file", 1)    # cut-point: run new code
    .live("agent", 2)          # downstream: observe effect
)
result = run_agent(...)

# Assert on live cut-point
assert session.captured_result("delete_file", 1)["blocked"] is True
```

### Layer 1 replay (injector API)

For single-envelope structural replay:

```python
from chronicle.replay import ReplayInjector
from chronicle import Envelope

envelope = Envelope.from_file("fixtures/envelopes/incident-2026-06-17-001.json")
injector = ReplayInjector(envelope)

def agent(state, inj):
    inj.stub_llm()
    inj.stub_tool("search_docs", {"query": "reset API key"})
    return {"finish_reason": "tool_calls"}

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

## Financial incident demos (record → cut-point test)

Three realistic billing/finance scenarios with minimal agent code. Each uses `@boundary` on `agent@1 → tool@1 → agent@2`.


| Scenario                    | Command name     | Incident                    |
| --------------------------- | ---------------- | --------------------------- |
| Refund amount = order ID    | `refund` or `1`  | $9.8M refund on a $47 order |
| Invoice currency mismatch   | `invoice` or `8` | €2M invoice sent as USD     |
| $1k notional → 1,000 shares | `trade` or `24`  | ~$190k sell instead of ~$1k |


```bash
# Record incident (ungated tool — bad outcome)
python examples/financial_incidents/run.py refund record
python examples/financial_incidents/run.py invoice record
python examples/financial_incidents/run.py trade record

# Cut-point test (stub agent@1, live gated tool, live agent@2)
python examples/financial_incidents/run.py refund test
python examples/financial_incidents/run.py invoice test
python examples/financial_incidents/run.py trade test

# All three in sequence
python examples/financial_incidents/run.py all record
python examples/financial_incidents/run.py all test

# Tests
pytest tests/test_financial_incidents.py -v
```

Scenario source (screenshot-friendly): `examples/financial_incidents/refund_order_id.py`, `invoice_currency.py`, `trade_notional.py`

Cut-point plan (each scenario): `stub agent@1` → `LIVE <tool>@1` (max-amount gate)`→`LIVE agent@2`

Gated fix (same pattern in each tool): refuse if amount exceeds a flat cap — `MAX_REFUND_CENTS` ($10k), `MAX_INVOICE_CENTS` ($100k), `MAX_ORDER_NOTIONAL_CENTS` ($5k).

## Deletion agent demo (record → visualize → cut-point test)

A test bench where an ungated `delete_file` tool deletes production data, then a cut-point test verifies the gated fix.

```bash
# 1. Record the incident (ungated tool deletes prod)
python examples/deletion_agent/record_incident.py

# 2. View trace in terminal (demo.sh will offer interactive UI next)
python examples/deletion_agent/show_trace.py

# 3. Interactive UI (timeline + graph + full envelope on click)
python examples/deletion_agent/show_trace.py --ui
# or: chronicle show-graph fixtures/traces/deletion-incident-001 --ui

# 4. Static HTML export
python examples/deletion_agent/show_trace.py --html trace.html

# 5. Cut-point replay demo (gated tool blocks prod)
python examples/deletion_agent/run_cutpoint_demo.py

# 6. Full test suite (separate from demo)
python scripts/run.py test
# or: pytest tests/test_deletion_cutpoint.py -v
```

Cut-point plan: `stub agent@1` → `LIVE delete_file@1` (gated)`→`LIVE agent@2`

Expected incident graph:

```
agent@1 → delete_file@1 (deleted prod) → agent@2
```

## Workflow

```
Annotate → Record → Visualize → Extract → Fix → Cut-point replay → Verify
    │         │          │          │       │           │              │
    │         │          │          │       │           │              └─ pytest / chronicle replay
    │         │          │          │       │           └─ ReplayPlan stub/live
    │         │          │          │       └─ Change target boundary code
    │         │          │          └─ fixtures/traces/ committed to git
    │         │          └─ show_trace --ui
    │         └─ @boundary in LIVE mode
    └─ @boundary on LLM + tool methods
```

## CLI

```bash
chronicle record                                    # Bootstrap tracing + instrumentation
chronicle extract --trace-id ID                     # Export envelopes to fixtures/
chronicle replay FIXTURE.json                       # Layer 1 deterministic replay
chronicle verify FIXTURE.json --layer2 --mock-judge # Layer 1 + Layer 2
chronicle show-graph fixtures/traces/TRACE --ui     # Interactive trace visualization
chronicle show-graph TRACE --html out.html          # Static HTML export
chronicle schema                                    # Print Envelope JSON Schema
chronicle list-fixtures                             # List committed envelope fixtures
```

## LangGraph integration (optional)

For LangGraph-specific node wrapping (alternative to `@boundary`):

```python
from chronicle.envelope.capture import EnvelopeRecorder
from chronicle.envelope.store import EnvelopeStore
from chronicle.instrumentation import instrument_graph_nodes

recorder = EnvelopeRecorder(
    store=EnvelopeStore(".chronicle/runs/envelopes.jsonl"),
    model_version="gpt-4o-2024-08-06",
    build_id="deploy-abc123",
)
wrapped_nodes = instrument_graph_nodes(recorder, {"agent": agent_node})
```

See `examples/langgraph_demo/agent.py`.

## Environment Variables


| Variable                     | Purpose                                                 |
| ---------------------------- | ------------------------------------------------------- |
| `CHRONICLE_BUILD_ID`         | Pin runtime build ID in envelope metadata               |
| `CHRONICLE_STORE`            | Default envelope store path                             |
| `PHOENIX_COLLECTOR_ENDPOINT` | Phoenix OTLP endpoint (default `http://localhost:4317`) |


## Project Structure

**Core vs examples:** only `chronicle/` is the installable library. Demos, screenshot assets, and interactive benches stay under `examples/`. Committed regression traces live in `fixtures/` (not package modules). See `examples/README.md`.

```
chronicle/                 # installable package (pip install -e .)
├── boundary.py            # @boundary decorator (record + replay + cut-point)
├── session.py             # runtime session, on_crossing hook, stub/live modes
├── execution_graph.py     # side graph builder (load/save/render)
├── visualizer.py          # HTML trace UI (library + CLI)
├── envelope/              # schema, capture, append-only store
├── replay/                # ReplayPlan, ReplayInjector, structural assertions
├── judge/                 # Layer 2 rubric + LLM-as-judge runner
├── instrumentation/       # OpenInference + LangGraph hooks
└── cli.py
fixtures/                  # committed regression data (not library code)
├── envelopes/             # single-step envelopes
└── traces/                # multi-step graphs (graph.json + envelopes)
examples/                  # demos / test benches (not imported by the package)
├── financial_incidents/   # refund, invoice, trade demos
├── deletion_agent/        # record → visualize → cut-point demo
└── langgraph_demo/        # LangGraph node wrapping example
scripts/                   # demo | test runners
tests/                     # unit + e2e (incl. cost-management on_crossing)
```

## License

MIT
