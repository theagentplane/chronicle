"""Layer 1: deterministic replay from envelope fixtures."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from chronicle.envelope.schema import ActionResult, Envelope, InputState
from chronicle.replay.assertions import AssertionResult, StructuralAssertions

_REPLAY_GUARD = "CHRONICLE_LAYER1_REPLAY"


@dataclass
class ReplayContext:
    """Injected state for deterministic Layer 1 execution."""

    envelope: Envelope
    input_state: InputState
    stubbed_completion: str | None
    stubbed_tool_results: dict[str, Any] = field(default_factory=dict)
    call_log: list[dict[str, Any]] = field(default_factory=list)


class LLMCallBlockedError(RuntimeError):
    """Raised when Layer 1 replay attempts a real LLM API call."""


def enable_replay_guard() -> None:
    os.environ[_REPLAY_GUARD] = "1"


def disable_replay_guard() -> None:
    os.environ.pop(_REPLAY_GUARD, None)


def is_replay_mode() -> bool:
    return os.environ.get(_REPLAY_GUARD) == "1"


def assert_no_llm_call() -> None:
    if is_replay_mode():
        raise LLMCallBlockedError(
            "Layer 1 replay must not call the LLM API. "
            "Inject recorded envelope state instead."
        )


class ReplayInjector:
    """
    Injects recorded envelope state for deterministic Layer 1 replay.

    The injector stubs LLM completions and tool results from the envelope,
    ensuring tests validate control flow without non-deterministic API calls.
    """

    def __init__(self, envelope: Envelope) -> None:
        self.envelope = envelope
        self.context = ReplayContext(
            envelope=envelope,
            input_state=envelope.input_state,
            stubbed_completion=envelope.action_result.completion,
        )

    def inject_state(self, state: dict[str, Any]) -> dict[str, Any]:
        """Merge recorded input state into a graph state dict."""
        injected = {**state, **self.envelope.input_state.graph_state}
        injected["messages"] = self.envelope.input_state.messages
        if self.envelope.input_state.system_prompt:
            injected["system_prompt"] = self.envelope.input_state.system_prompt
        injected["rag_chunks"] = [
            c.model_dump() for c in self.envelope.input_state.rag_chunks
        ]
        return injected

    def stub_llm(self, prompt: str | None = None) -> ActionResult:
        """Return the recorded completion without calling any LLM."""
        self.context.call_log.append({"type": "llm_stub", "prompt": prompt})
        return self.envelope.action_result

    def stub_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Return a stubbed tool result from the recorded envelope."""
        self.context.call_log.append(
            {"type": "tool_stub", "name": name, "arguments": arguments}
        )
        if name in self.context.stubbed_tool_results:
            return self.context.stubbed_tool_results[name]
        for tc in self.envelope.action_result.tool_calls:
            if tc.name == name:
                return {"status": "recorded", "tool": name, "arguments": tc.arguments}
        return {"status": "stubbed", "tool": name}

    def replay(
        self,
        agent_fn: Callable[[dict[str, Any], ReplayInjector], Any],
        *,
        initial_state: dict[str, Any] | None = None,
    ) -> tuple[Any, ReplayContext, list[AssertionResult]]:
        """
        Execute agent logic with injected envelope state.

        Returns (result, context, assertion_results).
        """
        enable_replay_guard()
        try:
            state = self.inject_state(initial_state or {})
            result = agent_fn(state, self)
            assertions = StructuralAssertions(self.envelope)
            results = assertions.run_all(result, self.context.call_log)
            return result, self.context, results
        finally:
            disable_replay_guard()
