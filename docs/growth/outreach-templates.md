# Outreach templates

Drafts only. Nothing here gets sent or posted until Tisha approves the exact text
per venue (see `program.md`: outreach is never autonomous). Every number below is
pulled straight from `docs/benchmark-results.json` or the README — no invented
stats. No em dashes or en dashes (repo style).

Common framing to stay consistent with the README's own positioning: Chronicle is
not a tracing dashboard or an eval framework, it is what makes a recorded agent run
replayable and testable. Scope is honestly narrow: control-flow and tool-safety
regressions caught deterministically from recorded incidents, not general model
quality.

---

## 1. Show HN

**Title (pick one, HN penalizes hype):**
- `Show HN: Chronicle – turn a production agent failure into a committed regression test`
- `Show HN: Record-and-replay for agent decision graphs, no live LLM calls on replay`

**Body:**

```
Chronicle records what an agent did at each decision point (LLM call, tool call,
routing choice) as an immutable "Envelope." When something goes wrong in
production, you commit the recording as a fixture under fixtures/traces/, then
write a cut-point test: stub everything upstream, run your fix live at the one
boundary that changed, and assert deterministically with no LLM calls on replay.

It's not a tracing dashboard or an eval framework, there are good ones already
(LangSmith, Langfuse, Phoenix). Chronicle is the piece that makes a recorded run
replayable and testable, and it sits alongside those tools rather than
replacing them.

Recording overhead in our benchmark harness is ~20-25us/crossing (~0.008% of a
300ms model call) and ~1.4KB/crossing on disk (examples/benchmark, numbers in
docs/benchmark-results.json). It has a LangGraph integration
(instrument_langgraph) and wraps OpenAI/Anthropic-style clients directly
(chronicle.wrap(client)) or plain functions (@boundary).

Honest scope: this catches control-flow and tool-safety regressions in
multi-agent systems, not model-quality drift. There's an optional LLM-as-judge
layer for meaning, but Layer 1 (deterministic replay) never calls a live model.

pip install agent-chronicle
GitHub: https://github.com/theagentplane/chronicle
Quick start: https://github.com/theagentplane/chronicle#quick-start

Happy to answer questions about the design, especially the cut-point mechanism
and what "boundary" does and doesn't capture (I/O only, not side effects).
```

---

## 2. r/LocalLLaMA

Framing: developer-tool, technical, skip the "why agents matter" preamble.

```
Built Chronicle: record-and-replay for agent decision graphs. If your agent's
prod incident is a plain text trace you can't re-run, this turns it into a
committed fixture and a deterministic regression test (no live LLM calls on
replay).

@boundary decorator, or chronicle.wrap(client) for zero-decorator recording,
or instrument_langgraph(nodes) if you're on LangGraph. Layer 1 replay is
structural/deterministic; there's an optional LLM-as-judge layer if you want
to check meaning instead of exact output.

MIT licensed, pip install agent-chronicle.
https://github.com/theagentplane/chronicle

Genuinely curious if this matches how people here are already debugging agent
regressions, or if most of you are rolling your own trace-replay scripts.
```

---

## 3. r/MachineLearning

Framing: slightly more academic/methods-oriented, this subreddit is stricter
about self-promotion, lead with the problem and be upfront it's your project.

```
[P] Chronicle: deterministic replay for regression-testing LLM agents

Sharing a project I've been building: a record-and-replay system for agent
decision graphs. The problem it targets is narrow and specific: a production
agent fails, you want to reproduce that exact failure as a committed test, fix
one component, and verify the fix without re-running the whole agent against a
live model (nondeterministic, slow, costs money).

Mechanism: an immutable "Envelope" captures I/O at each decision boundary
(LLM call, tool call, routing choice). Cut-point replay lets you stub every
boundary upstream of the one you changed, run that one live, and assert
deterministically. Two verification layers: structural replay (no LLM calls)
for control flow, and an optional LLM-as-judge layer for output meaning.

This is not a general observability or eval framework, it complements those.
Benchmark numbers (methodology + harness in examples/benchmark) are in the
repo: ~20-25us/crossing recording overhead, ~1.4KB/crossing storage.

MIT license, source + docs: https://github.com/theagentplane/chronicle

Feedback on the approach (especially where cut-point replay breaks down) is
what I'm actually here for, not just the link.
```

---

## 4. r/AI_Agents

Framing: more practitioner/building-in-public tone fits this sub.

```
Shipped a fix for something that kept biting me building multi-agent systems:
reproducing a specific prod failure without needing the whole agent + a live
model to re-run every time.

Chronicle records each decision boundary (LLM call, tool call, routing
decision) as an immutable Envelope, then lets you commit an incident as a
fixture and cut-point test just the one boundary you fixed, live, with
everything else stubbed from the recording. No LLM calls on replay.

Works with @boundary, or zero-decorator via chronicle.wrap(openai_client),
or instrument_langgraph(nodes) for LangGraph.

pip install agent-chronicle · https://github.com/theagentplane/chronicle

Scope is honest: this is for control-flow/tool-safety bugs, not for chasing
model-quality regressions, there's a separate LLM-as-judge layer for that if
you want it.
```

---

## 5. r/LangChain

Framing: lead with the LangGraph integration specifically.

```
If you're on LangGraph and have hit "the agent regressed and I can't cheaply
tell you why without re-running the whole graph against a live model" -
Chronicle has an instrument_langgraph(nodes) entry point that records every
node crossing as an Envelope, then lets you replay a past run deterministically
(stub upstream, run your fix live at one node) without calling the model again.

Two verification layers: structural replay for control flow (no LLM calls),
optional LLM-as-judge for output meaning.

https://github.com/theagentplane/chronicle - pip install agent-chronicle,
MIT licensed. Would love feedback from anyone running LangGraph in prod on
whether the node-level granularity is the right cut for your failures.
```

---

## 6. LangChain Community Slack intro

Post in an introductions/showcase channel, not a DM blast.

```
Hi all, I'm Tisha, building Chronicle, a record-and-replay system for agent
decision graphs (MIT, pip install agent-chronicle). It has an
instrument_langgraph(nodes) integration that records LangGraph node crossings
and lets you replay a past run deterministically to regression-test a fix,
no live model calls needed on replay.

https://github.com/theagentplane/chronicle

Happy to answer questions, and genuinely interested in how people here
currently reproduce a specific prod LangGraph failure as a test.
```

---

## 7. AIE WF / Latent Space follow-up (warm, not cold)

Only use this framing, referencing the actual talk, adjust to match what was
actually said in the AIE WF 2026 talk before sending:

```
Hi [name], I spoke at AIE WF 2026 about Chronicle, record-and-replay for agent
decision graphs. Wanted to share what's shipped since: cut-point replay,
LangGraph + OpenTelemetry integrations, pluggable storage (SQLite/remote), and
a benchmark harness with real incident scenarios (numbers in the repo). MIT
licensed, on PyPI as agent-chronicle now.

https://github.com/theagentplane/chronicle

Would love to share it with the Latent Space community if there's a good venue
for it, and happy to do a short follow-up writeup if useful.
```

---

## 8. Reply/comment to Hamel Husain (not cold email)

Draft for a reply on X or a comment on a specific relevant post of his, adjust
to actually respond to what he wrote rather than posting this verbatim:

```
This resonates with something we built Chronicle around: eval-driven
development is great for output quality, but a lot of agent failures are
control-flow/tool-safety bugs (wrong tool call, ungated destructive action,
retry logic), and those need a different kind of test, deterministic replay
of the exact failing trace, not another eval run. Chronicle commits the
production incident as a fixture and lets you cut-point test just the fixed
boundary. Curious whether that distinction (eval failures vs replay-testable
control-flow failures) matches what you're seeing in the course.
https://github.com/theagentplane/chronicle
```

---

## 9. X / Twitter launch post

```
Chronicle: record-and-replay for agent decision graphs.

Turn a production agent failure into a committed regression test. Fix one
boundary, replay the rest from the recording, no live LLM calls needed to
verify the fix.

pip install agent-chronicle
MIT, LangGraph + OTel integrations, cut-point replay.

https://github.com/theagentplane/chronicle
```

---

## 10. Awesome-list PR description (reuse for all five lists)

```
Add Chronicle (agent-chronicle): record-and-replay for agent decision graphs.
Records LLM/tool/routing decisions as immutable Envelopes; supports committing
production incidents as fixtures and cut-point replay testing (stub upstream,
run the fix live, no LLM calls on replay). MIT licensed, pip install
agent-chronicle. https://github.com/theagentplane/chronicle
```

Match each list's existing entry format/section before opening the PR, some
enforce alphabetical order or a strict one-line description length.
