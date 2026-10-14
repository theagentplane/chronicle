# Examples

Runnable demos for Chronicle 1.0. Each one calls a **live model** and saves to a **real control
plane**: the `agentplane-control-plane` service, started inside the demo on a free port with a
throwaway SQLite database. Nothing is stored after the demo ends.

## Run them

```bash
pip install agent-chronicle agentplane-control-plane openai anthropic langgraph \
    langchain-openai starlette uvicorn
export OPENAI_API_KEY=...            # all demos
export ANTHROPIC_API_KEY=...         # frameworks.py only; skipped when not set

python examples/record_and_replay.py
python examples/multi_agent.py
python examples/frameworks.py
python examples/incidents.py
```

Use `DEMO_OPENAI_MODEL` and `DEMO_ANTHROPIC_MODEL` to pick the models (defaults `gpt-4o-mini` and
`claude-haiku-5-5`). Model calls cost real tokens; each demo makes a handful.

## What each one shows

| Demo | Shows |
|---|---|
| [`record_and_replay.py`](record_and_replay.py) | An agent deletes a production file on the model's say-so. The request is saved, the fix (a guard in the tool) is added, and the **saved request is replayed**: the model's recorded answer is reused, only the tool runs live, and the delete is blocked. |
| [`multi_agent.py`](multi_agent.py) | An orchestrator calls a specialist service over HTTP. **One trace across two services**: the specialist's span is parented on the orchestrator's outgoing call. Printed as a tree read back from the control plane. |
| [`frameworks.py`](frameworks.py) | The same task in the OpenAI SDK, Anthropic SDK, LangChain and LangGraph. The Chronicle lines are marked `# chronicle`. The saved model call has the **same canonical fields** whichever framework or provider made it. |
| [`incidents.py`](incidents.py) | Six costly agent mistakes (a refund of millions, a wrong-currency invoice, a 1,000-share sale, an email blast, an injected payout account, a production delete). Each is recorded, then the fix is **proven by replay**. |

In `incidents.py` the *mistake* is a deterministic planning step, so it reproduces on every run;
the message to the user is written by the live model. Nothing in any demo touches your disk or
sends anything: the tools are simulated.

## The Chronicle calls used

| Call | What it does |
|---|---|
| `chronicle.configure(...)` | Point Chronicle at a control plane (`_support/plane.py` does this). |
| `chronicle.wrap(client)` | Record every model call of an OpenAI, Anthropic or LiteLLM client. |
| `@chronicle.boundary(name, kind="tool")` | Record a function as a decision point. |
| `chronicle.record(name)` / `chronicle.span(headers)` | Open a trace, or join the caller's. |
| `chronicle.ChronicleMiddleware` | Open a span per request in an ASGI service. |
| `chronicle.instrument_httpx()` | Record calls to peer agents and carry the trace header. |
| `chronicle.instrument(graph)` | Wrap every node of a LangGraph graph. |
| `chronicle.replay_trace(trace_id, span_id, ReplayPlan().run("tool", 1))` | Replay a saved span with chosen boundaries live. |

`_support/` holds the shared helpers (the local control plane, the model clients, the trace
printer). The smoke test `tests/e2e/test_examples.py` runs every demo against a scripted model so
the demos stay working without a key.
