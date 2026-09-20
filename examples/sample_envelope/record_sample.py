#!/usr/bin/env python3
"""Record a single LLM envelope with retrieved context (no API keys needed).

A support agent retrieves one docs chunk, then a stub model answers by requesting a
``search_docs`` tool call. The recorded envelope is the sample used by the schema,
replay and judge tests.

    python examples/sample_envelope/record_sample.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import chronicle  # noqa: E402
from chronicle import boundary  # noqa: E402

OUT = ROOT / "fixtures" / "envelopes" / "support-agent-001.json"

DOCS = [
    {
        "chunk_id": "doc-42",
        "content": "API keys can be reset from Settings > API Keys > Regenerate.",
        "source": "docs/api-keys.md",
        "score": 0.92,
        "index_version": "v3.2.1",
    }
]


def retrieve(question: str) -> list[dict]:
    return [c for c in DOCS if "api key" in question.lower()]


@boundary("agent", kind="llm")
def agent(messages: list[dict], system_prompt: str, rag_chunks: list[dict]) -> dict:
    """Stub model: answer from the retrieved chunk and ask for a follow-up search."""
    return {
        "completion": rag_chunks[0]["content"] if rag_chunks else "I don't know.",
        "tool_calls": [{"id": "call_1", "name": "search_docs", "arguments": {"query": "reset API key"}}],
        "finish_reason": "tool_calls",
        "model": "stub-support-model-1",
        "temperature": 0.0,
        "top_p": 1.0,
        "max_tokens": 1024,
        "seed": 42,
        "usage": {"prompt_tokens": 256, "completion_tokens": 24},
    }


def main() -> None:
    question = "How do I reset my API key?"
    with chronicle.record("support-agent-001") as session:
        agent(
            messages=[{"role": "user", "content": question}],
            system_prompt="You are a helpful support agent. Use search_docs for factual answers.",
            rag_chunks=retrieve(question),
        )
    (envelope,) = session.envelopes
    envelope.write_file(str(OUT))
    print(f"wrote {OUT}")
    print(f"trace_id={envelope.trace_id} envelope_id={envelope.envelope_id}")


if __name__ == "__main__":
    main()
