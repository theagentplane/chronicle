"""The judge runner scores an envelope with a mock client (no API calls)."""

import pytest
from agentplane_primitives.enums import Kind, MessageRole, State, Status
from agentplane_primitives.models import (
    Envelope,
    EnvelopeStatus,
    LlmInput,
    LlmOutput,
    Message,
    TextBlock,
    Usage,
)
from agentplane_primitives.utils import new_envelope_id, new_span_id, new_trace_id

from chronicle.judge import EvaluationRubric, JudgeRunner, MockJudgeClient
from chronicle.timing_utils import utc_now


@pytest.fixture
def envelope() -> Envelope:
    now = utc_now()
    return Envelope(
        envelope_id=new_envelope_id(),
        span_id=new_span_id(),
        trace_id=new_trace_id(),
        name="agent.chat",
        kind=Kind.LLM,
        envelope_status=EnvelopeStatus(
            state=State.CLOSED, status=Status.SUCCESS, started_at=now, ended_at=now
        ),
        input=LlmInput(
            model="gpt-4o",
            messages=[Message(role=MessageRole.USER, content="How do I reset my API key?")],
            raw={"rag_chunks": ["API keys can be reset in Settings."]},
        ),
        output=LlmOutput(
            content=[TextBlock(text="Open Settings and choose reset.")],
            usage=Usage(input=10, output=5),
        ),
    )


def test_mock_judge_passes(envelope: Envelope) -> None:
    result = JudgeRunner(MockJudgeClient(pass_all=True)).evaluate(envelope)
    assert result.overall_passed
    assert all(s.passed for s in result.scores)


def test_mock_judge_fails(envelope: Envelope) -> None:
    result = JudgeRunner(MockJudgeClient(pass_all=False)).evaluate(envelope)
    assert not result.overall_passed


def test_rubric_generates_judge_prompt() -> None:
    prompt = EvaluationRubric().judge_prompt(
        input_context="user question",
        completion="answer",
        rag_chunks=["API keys can be reset in Settings."],
    )
    assert "grounding" in prompt
    assert "API keys can be reset" in prompt
