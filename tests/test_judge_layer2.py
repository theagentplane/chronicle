"""Layer 2: LLM-as-judge evaluation tests."""

from pathlib import Path

import pytest

from chronicle.envelope.schema import Envelope
from chronicle.judge import EvaluationRubric, JudgeRunner, MockJudgeClient

FIXTURES = Path(__file__).parent.parent / "fixtures" / "envelopes"


@pytest.fixture
def sample_envelope() -> Envelope:
    return Envelope.from_file(str(FIXTURES / "incident-2026-06-17-001.json"))


@pytest.mark.layer2
def test_mock_judge_passes(sample_envelope: Envelope):
    runner = JudgeRunner(MockJudgeClient(pass_all=True))
    result = runner.evaluate(sample_envelope)
    assert result.overall_passed
    assert all(s.passed for s in result.scores)


@pytest.mark.layer2
def test_mock_judge_fails(sample_envelope: Envelope):
    runner = JudgeRunner(MockJudgeClient(pass_all=False))
    result = runner.evaluate(sample_envelope)
    assert not result.overall_passed


@pytest.mark.layer2
def test_rubric_generates_judge_prompt(sample_envelope: Envelope):
    rubric = EvaluationRubric()
    prompt = rubric.judge_prompt(
        input_context="user question",
        completion=sample_envelope.action_result.completion or "",
        rag_chunks=[c.content for c in sample_envelope.input_state.rag_chunks],
    )
    assert "grounding" in prompt
    assert "API keys can be reset" in prompt
