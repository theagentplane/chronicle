"""Graph-boundary envelope capture."""

from __future__ import annotations

import functools
import os
import uuid
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

from chronicle.envelope.schema import (
    ActionResult,
    ContextMetadata,
    Envelope,
    InputState,
    RagChunk,
    SamplingParams,
    ToolCall,
    ToolSchema,
)
from chronicle.envelope.store import EnvelopeStore

P = ParamSpec("P")
R = TypeVar("R")


def _default_build_id() -> str:
    return os.environ.get("CHRONICLE_BUILD_ID", "dev-local")


class EnvelopeRecorder:
    """
    Captures immutable envelopes at graph node boundaries.

    Wrap LangGraph nodes (or any callable boundary) to record input state,
    metadata, and structured outputs as append-only envelopes.
    """

    def __init__(
        self,
        store: EnvelopeStore | str | None = None,
        *,
        model_version: str,
        build_id: str | None = None,
        sampling_params: SamplingParams | None = None,
        tool_schemas: list[ToolSchema] | None = None,
        framework: str = "langgraph",
        trace_id: str | None = None,
    ) -> None:
        if isinstance(store, str):
            store = EnvelopeStore(store)
        self.store = store
        self.model_version = model_version
        self.build_id = build_id or _default_build_id()
        self.sampling_params = sampling_params or SamplingParams()
        self.tool_schemas = tool_schemas or []
        self.framework = framework
        self.trace_id = trace_id

    def _build_metadata(self, node_id: str) -> ContextMetadata:
        return ContextMetadata(
            model_version=self.model_version,
            sampling_params=self.sampling_params,
            build_id=self.build_id,
            tool_schemas=self.tool_schemas,
            framework=self.framework,
            node_id=node_id,
            trace_id=self.trace_id,
        )

    def record(
        self,
        node_id: str,
        input_state: InputState,
        action_result: ActionResult,
        *,
        trace_id: str | None = None,
    ) -> Envelope:
        envelope = Envelope(
            trace_id=trace_id or self.trace_id or str(uuid.uuid4()),
            node_id=node_id,
            metadata=self._build_metadata(node_id),
            input_state=input_state,
            action_result=action_result,
        )
        if self.store is not None:
            self.store.append(envelope)
        return envelope

    def wrap_node(
        self,
        node_id: str,
        *,
        extract_input: Callable[[dict[str, Any]], InputState] | None = None,
        extract_result: Callable[[dict[str, Any], Any], ActionResult] | None = None,
    ) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """
        Decorator that records an envelope on every node invocation.

        Provide extract_input/extract_result to map framework-specific state
        into the canonical envelope schema.
        """

        def decorator(fn: Callable[P, R]) -> Callable[P, R]:
            @functools.wraps(fn)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                state = args[0] if args else kwargs.get("state", {})
                if not isinstance(state, dict):
                    state = {}

                if extract_input:
                    input_state = extract_input(state)
                else:
                    input_state = InputState(
                        messages=state.get("messages", []),
                        system_prompt=state.get("system_prompt"),
                        rag_chunks=[
                            RagChunk(**c) if isinstance(c, dict) else c
                            for c in state.get("rag_chunks", [])
                        ],
                        graph_state=state,
                    )

                result = fn(*args, **kwargs)

                if extract_result:
                    action_result = extract_result(state, result)
                else:
                    action_result = _default_extract_result(result)

                self.record(node_id, input_state, action_result)
                return result

            return wrapper

        return decorator


def _default_extract_result(result: Any) -> ActionResult:
    if isinstance(result, dict):
        tool_calls = [
            ToolCall(
                id=tc.get("id"),
                name=tc.get("name", ""),
                arguments=tc.get("arguments", tc.get("args", {})),
            )
            for tc in result.get("tool_calls", [])
        ]
        return ActionResult(
            tool_calls=tool_calls,
            completion=result.get("completion") or result.get("output"),
            finish_reason=result.get("finish_reason"),
            token_usage=result.get("token_usage", {}),
        )
    if isinstance(result, str):
        return ActionResult(completion=result)
    return ActionResult(completion=str(result))


def messages_to_input_state(
    messages: list[dict[str, Any]],
    *,
    rag_chunks: list[RagChunk] | None = None,
    system_prompt: str | None = None,
    graph_state: dict[str, Any] | None = None,
) -> InputState:
    return InputState(
        messages=messages,
        system_prompt=system_prompt,
        rag_chunks=rag_chunks or [],
        graph_state=graph_state or {},
    )


def completion_to_action_result(
    completion: str,
    *,
    tool_calls: list[ToolCall] | None = None,
    finish_reason: str | None = None,
    token_usage: dict[str, int] | None = None,
) -> ActionResult:
    return ActionResult(
        tool_calls=tool_calls or [],
        completion=completion,
        finish_reason=finish_reason,
        token_usage=token_usage or {},
    )
