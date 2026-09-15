# Outreach target list

Composition: community venues (where hundreds of interested people self-select) plus
a short list of specific, real, verifiable people worth a personalized note. I did not
force this to 100 individual names — see "Why not 100 individual contacts" at the
bottom. Every entry below is a real, currently-existing venue or person found via
search on 2026-08-09; confidence is marked because "currently exists" and "will
respond" are different things.

## A. Warm lead (start here — not cold outreach)

- **AI Engineer World's Fair (AIE WF) community / Latent Space Discord** — run by
  Shawn Wang (swyx); described as the closest thing to a single home for applied AI
  engineering in 2026, very active Discord + regular meetups. **Tisha already spoke
  at AIE WF 2026** — this is a warm relationship, not a cold pitch. A short "here's
  what shipped since the talk" post/message fits naturally.
  Confidence: **verified** (community exists, active); the prior-talk relationship is
  from our own project history, not a web search.

## B. Awesome-lists (PR submissions — concrete, low-risk, durable backlinks)

Adding Chronicle to a maintained curated list is not outreach in the cold-email
sense — it's a normal, expected OSS contribution (a short PR: one line + one-sentence
description), reviewed by that list's own maintainer on their own terms.

| List | URL | Fit |
|---|---|---|
| aloth/awesome-ai-agents | https://github.com/aloth/awesome-ai-agents | Tracing/evals/observability section |
| benchflow-ai/awesome-evals | https://github.com/benchflow-ai/awesome-evals | Agent-specific evaluation infra |
| goabiaryan/awesome-observability | https://github.com/goabiaryan/awesome-observability | LLM/agent observability tools |
| danielrosehill/Awesome-AI-Evaluations-Tools | https://github.com/danielrosehill/Awesome-AI-Evaluations-Tools | Agentic AI eval tooling |
| Picrew/awesome-agent-harness | https://github.com/Picrew/awesome-agent-harness | Agent harness / tracing / eval analytics |

Confidence: **verified** (all five exist and are actively maintained as of this
search). Each PR should be reviewed by Tisha before submitting — some list
maintainers have strict contribution formats.

## C. Community venues (posts, not cold DMs — people opt in by reading)

| Venue | Why it fits | Confidence |
|---|---|---|
| Show HN (news.ycombinator.com) | Highest-leverage single post for a dev tool at this stage; self-selecting technical audience | Verified (venue exists; outcome is inherently unpredictable) |
| r/LocalLLaMA | Widely regarded as the top subreddit for LLM developers/tooling | Verified |
| r/MachineLearning | Broader ML audience, good for the "record/replay as regression testing" framing | Verified |
| r/AI_Agents | Fastest-growing agent-specific subreddit in 2026 | Verified |
| r/LangChain | Direct audience overlap — Chronicle already has a LangGraph integration | Verified |
| LangChain Community Slack (join-community page) | 30k+ developer community; note it's **Slack now, not Discord** (corrects an earlier assumption) | Verified |

## D. Specific people (short, personal note — not a template blast)

| Person | Why | Contact approach | Confidence |
|---|---|---|---|
| **Hamel Husain** (hamel.dev, evals course w/ Shreya Shankar) | The most prominent current voice specifically on LLM/agent eval methodology; writes extensively on eval-driven development for agents in 2026 — a natural, substantive audience for a regression-testing tool, not a generic observability pitch | Reply/quote to a relevant recent post of his on X (`@HamelHusain`), or a thoughtful comment on a relevant hamel.dev post — **not** a cold email, no personal address found or assumed | Person/relevance verified via search; no personal email sourced (none should be guessed) |

**Why only one confidently-verified individual, not 15-20:** finding a real person's
correct, current, personal contact information requires per-person research I can't
responsibly shortcut — search results surface *articles about* the space, not
verified inboxes. Padding this list with plausible-sounding names and guessed
contact methods would fail the "no fabricated contacts" rule in `program.md`. If
Tisha has existing personal contacts (past conference connections, GitHub follows,
people who've starred/commented already) worth a note, those are higher-confidence
than anything I can source cold — worth adding here from her own network rather
than mine.

## Suggested order

1. AIE WF / Latent Space (warm, already-earned).
2. Awesome-list PRs (five small, low-effort, durable).
3. Show HN (single highest-leverage post — pick a quiet week, have the top comment
   response ready).
4. Subreddit posts (can follow within the same week; each needs its own framing,
   not a copy-paste of the HN post — see `outreach-templates.md`).
5. Hamel Husain reply/comment, timed to a specific relevant post of his rather than
   sent cold with no context.
