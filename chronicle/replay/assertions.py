"""Structural assertions for Layer 1 replay — no word-for-word output matching."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from chronicle.envelope.schema import Envelope


@dataclass
class AssertionResult:
    name: str
    passed: bool
    message: str


@dataclass
class StructuralAssertions:
    """
    Assert on control-flow structure from a replayed envelope fixture.

    Layer 1 validates:
    - Correct tools were called (name + argument keys, not exact values)
    - Expected routing / finish reason
    - Required fields present in result
    """

    envelope: Envelope
    expected_tool_names: list[str] | None = None
    required_result_keys: list[str] = field(default_factory=list)
    forbid_tool_names: list[str] = field(default_factory=list)

    def assert_tools_called(self, call_log: list[dict[str, Any]]) -> AssertionResult:
        expected = self.expected_tool_names or [
            tc.name for tc in self.envelope.action_result.tool_calls
        ]
        actual = [
            entry["name"]
            for entry in call_log
            if entry.get("type") == "tool_stub"
        ]
        missing = set(expected) - set(actual)
        if missing:
            return AssertionResult(
                "tools_called",
                False,
                f"Missing tool calls: {missing}. Actual: {actual}",
            )
        forbidden = set(self.forbid_tool_names) & set(actual)
        if forbidden:
            return AssertionResult(
                "tools_called",
                False,
                f"Forbidden tools called: {forbidden}",
            )
        return AssertionResult("tools_called", True, f"All expected tools called: {expected}")

    def assert_tool_argument_keys(
        self, call_log: list[dict[str, Any]]
    ) -> AssertionResult:
        for recorded in self.envelope.action_result.tool_calls:
            matching = [
                e
                for e in call_log
                if e.get("type") == "tool_stub" and e.get("name") == recorded.name
            ]
            if not matching:
                continue
            actual_args = matching[0].get("arguments", {})
            expected_keys = set(recorded.arguments.keys())
            actual_keys = set(actual_args.keys())
            if expected_keys and not expected_keys.issubset(actual_keys):
                return AssertionResult(
                    "tool_argument_keys",
                    False,
                    f"Tool '{recorded.name}' missing keys: {expected_keys - actual_keys}",
                )
        return AssertionResult("tool_argument_keys", True, "Tool argument keys match")

    def assert_result_structure(self, result: Any) -> AssertionResult:
        if not self.required_result_keys:
            return AssertionResult("result_structure", True, "No required keys specified")
        if not isinstance(result, dict):
            return AssertionResult(
                "result_structure",
                False,
                f"Expected dict result, got {type(result).__name__}",
            )
        missing = set(self.required_result_keys) - set(result.keys())
        if missing:
            return AssertionResult(
                "result_structure",
                False,
                f"Missing result keys: {missing}",
            )
        return AssertionResult("result_structure", True, "Result structure valid")

    def assert_finish_reason(self, result: Any) -> AssertionResult:
        expected = self.envelope.action_result.finish_reason
        if expected is None:
            return AssertionResult("finish_reason", True, "No finish_reason to assert")
        actual = result.get("finish_reason") if isinstance(result, dict) else None
        if actual != expected:
            return AssertionResult(
                "finish_reason",
                False,
                f"Expected finish_reason={expected!r}, got {actual!r}",
            )
        return AssertionResult("finish_reason", True, f"finish_reason={expected!r}")

    def assert_no_llm_calls(self, call_log: list[dict[str, Any]]) -> AssertionResult:
        llm_calls = [e for e in call_log if e.get("type") == "llm_api_call"]
        if llm_calls:
            return AssertionResult(
                "no_llm_calls",
                False,
                f"Layer 1 detected {len(llm_calls)} real LLM API call(s)",
            )
        return AssertionResult("no_llm_calls", True, "No real LLM API calls")

    def run_all(
        self, result: Any, call_log: list[dict[str, Any]]
    ) -> list[AssertionResult]:
        return [
            self.assert_tools_called(call_log),
            self.assert_tool_argument_keys(call_log),
            self.assert_result_structure(result),
            self.assert_finish_reason(result),
            self.assert_no_llm_calls(call_log),
        ]

    def all_passed(self, results: list[AssertionResult]) -> bool:
        return all(r.passed for r in results)
