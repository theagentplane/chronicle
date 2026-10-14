# Onboarding: record and replay your agent

A step-by-step guide. By the end you will have recorded a request to the control plane, followed a
call to a second agent, and replayed the request without the LLM.

> This guide is for 1.0. If you are coming from 0.5, read the
> [migration note](migration-0.5-to-1.0.md) first.

## 0. The one idea

An agent is a series of **decisions**: an **LLM call** (the model decides what to do) and a **tool
call** (`search`, `query_db`, `refund`, a call to another agent). Chronicle calls each one a
**boundary** and records what crossed it. One service's handling of a request is a **span**; a
request across services is a **trace**.

Your only job is to tell Chronicle which calls are boundaries and where to save.

## 1. Install and point at a control plane

```bash
pip install agent-chronicle
```

You need a running control plane (see the
[control-plane repository](https://github.com/theagentplane/control-plane)). Then:

```python
import chronicle

chronicle.configure(
    control_plane_url="http://localhost:8000",
    api_key="dev-key",
    service_name="my-agent",
)
```

The same settings can come from `CHRONICLE_CONTROL_PLANE_URL`, `CHRONICLE_API_KEY` and
`CHRONICLE_SERVICE_NAME`.

## 2. Mark the boundaries

```python
from openai import OpenAI

client = chronicle.wrap(OpenAI())  # every model call, with provider, model and usage


@chronicle.boundary("search", kind="tool")
def search(query: str) -> dict: ...
```

Put `@boundary` on decision nodes, not on the whole agent runner. Inputs and outputs should be
JSON-serializable, because replay hands the recorded JSON back.

## 3. Record a request

```python
with chronicle.record("first-run", labels={"session_id": "s1"}) as session:
    answer = run_agent("what is the refund policy?")

print(session.trace_id, session.span_id)  # the ids you replay with
```

In a web service use the middleware instead, so each request is its own span:

```python
app.add_middleware(chronicle.ChronicleMiddleware, service="my-agent")
```

## 4. Follow a call to another agent

```python
chronicle.configure(inject_hosts=["billing-agent.internal"])
chronicle.instrument_httpx()
```

Calls to `billing-agent.internal` are recorded as tool envelopes and carry the `traceparent` header.
The other agent (with the middleware) joins the same trace, and its span's `parent_envelope_id` is
your outbound call. Nothing else is sent to the LLM provider or any other host.

## 5. Replay it

```python
from chronicle import ReplayPlan

with chronicle.replay_trace(trace_id, span_id) as run:  # everything stubbed
    answer = run_agent("what is the refund policy?")

plan = ReplayPlan().run("search", 1)  # one boundary live (a cut-point)
with chronicle.replay_trace(trace_id, span_id, plan) as run:
    run_agent("what is the refund policy?")
    assert run.captured_result("search", 1)["hits"]
```

A stubbed boundary returns the recorded `output.raw` and makes no call; nothing is written during
replay. Matching is by boundary **name plus call count**, so a fix that calls a boundary more often
than the recording has raises `ReplayMismatchError`.

## 6. Make it safe for production

```python
chronicle.configure(default_redactors=True)  # mask API keys, tokens, JWTs before sending
```

Add your own redactors for personal data, and read [SECURITY.md](../SECURITY.md).

## Where to go next

- [README](../README.md) for the configuration table, hooks and limitations
- [Technical design](rfcs/chronicle-technical-design.md) for why it is built this way
- [Architecture decisions](adr/README.md)
