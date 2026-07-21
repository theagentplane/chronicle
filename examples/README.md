# Chronicle examples

Demos and test benches live here — **not** in the installable `chronicle` package.

| Path | Purpose |
|------|---------|
| `deletion_agent/` | Record → visualize → cut-point replay demo |
| `financial_incidents/` | Refund / invoice / trade incident demos (+ screenshot assets) |
| `langgraph_demo/` | Optional LangGraph node-wrapping example |

**Core library** (importable): `chronicle/` — `@boundary`, session, envelopes, replay, judge, CLI, visualizer API.

**Regression fixtures** (committed traces/envelopes): `fixtures/` — used by demos and pytest; not shipped as package code.

**Integration point for external cost observers** (e.g. TokenOps): set `session.on_crossing` — see `tests/test_cost_management_e2e.py`. Chronicle does not import cost-management products.
