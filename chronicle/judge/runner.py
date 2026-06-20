"""Layer 2: LLM-as-judge evaluation runner."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from chronicle.envelope.schema import Envelope
from chronicle.judge.rubric import Criterion, EvaluationRubric, RubricScore


class JudgeClient(Protocol):
    def complete(self, prompt: str) -> str: ...


@dataclass
class EvaluationResult:
    envelope_id: str
    scores: list[RubricScore]
    overall_passed: bool
    raw_judge_response: str


class JudgeRunner:
    """
    Layer 2 evaluation using LLM-as-a-judge.

    Assesses meaning (grounding, safety, refusal) rather than bitwise equality,
    since re-prompting changes hashes in non-deterministic systems.
    """

    def __init__(
        self,
        client: JudgeClient,
        rubric: EvaluationRubric | None = None,
    ) -> None:
        self.client = client
        self.rubric = rubric or EvaluationRubric()

    def evaluate(self, envelope: Envelope) -> EvaluationResult:
        input_text = json.dumps(envelope.input_state.messages, indent=2)
        completion = envelope.action_result.completion or ""
        rag_chunks = [c.content for c in envelope.input_state.rag_chunks]

        prompt = self.rubric.judge_prompt(
            input_context=input_text,
            completion=completion,
            rag_chunks=rag_chunks,
        )
        raw = self.client.complete(prompt)
        scores, overall = self._parse_response(raw)
        return EvaluationResult(
            envelope_id=envelope.envelope_id,
            scores=scores,
            overall_passed=overall,
            raw_judge_response=raw,
        )

    def _parse_response(self, raw: str) -> tuple[list[RubricScore], bool]:
        try:
            start = raw.index("{")
            end = raw.rindex("}") + 1
            data = json.loads(raw[start:end])
        except (ValueError, json.JSONDecodeError):
            return [
                RubricScore(
                    criterion=Criterion.RELEVANCE,
                    score=0.0,
                    rationale=f"Failed to parse judge response: {raw[:200]}",
                    passed=False,
                )
            ], False

        scores: list[RubricScore] = []
        for item in data.get("scores", []):
            try:
                criterion = Criterion(item["criterion"])
            except (KeyError, ValueError):
                continue
            score = float(item.get("score", 0.0))
            scores.append(
                RubricScore(
                    criterion=criterion,
                    score=score,
                    rationale=item.get("rationale", ""),
                    passed=item.get("passed", score >= self.rubric.pass_threshold),
                )
            )

        overall = data.get("overall_passed", all(s.passed for s in scores))
        return scores, overall


class MockJudgeClient:
    """Deterministic judge for testing Layer 2 plumbing without API calls."""

    def __init__(self, *, pass_all: bool = True) -> None:
        self.pass_all = pass_all

    def complete(self, prompt: str) -> str:
        passed = self.pass_all
        return json.dumps(
            {
                "scores": [
                    {
                        "criterion": "grounding",
                        "score": 0.9 if passed else 0.3,
                        "rationale": "mock judge",
                        "passed": passed,
                    },
                    {
                        "criterion": "safety",
                        "score": 0.95 if passed else 0.2,
                        "rationale": "mock judge",
                        "passed": passed,
                    },
                ],
                "overall_passed": passed,
            }
        )


class OpenAIJudgeClient:
    """Judge client backed by OpenAI-compatible chat completions."""

    def __init__(
        self,
        *,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        if client is None:
            try:
                from openai import OpenAI

                client = OpenAI(api_key=api_key)
            except ImportError as e:
                raise ImportError(
                    "Install chronicle with judge extras: pip install chronicle[judge]"
                ) from e
        self._client = client
        self.model = model

    def complete(self, prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return response.choices[0].message.content or ""
