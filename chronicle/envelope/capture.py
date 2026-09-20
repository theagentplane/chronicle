"""Graph-boundary envelope capture."""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

from chronicle.config import is_enabled
from chronicle.envelope.genai import AttributeValue, LLMRequest, SamplingParams, ToolSchema
from chronicle.envelope.schema import (
    Envelope,
    Input,
    LLMOutput,
    Message,
    Output,
    Status,
    ToolCall,
    Usage,
)
from chronicle.envelope.store import EnvelopeStore
from chronicle.ids import new_trace_id
from chronicle.session import usage_from

P = ParamSpec("P")
R = TypeVar("R")


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
        model: str,
        sampling_params: SamplingParams | None = None,
        tool_schemas: list[ToolSchema] | None = None,
        trace_id: str | None = None,
        redactors: list[Callable[[str], str]] | None = None,
    ) -> None:
        if isinstance(store, str):
            store = EnvelopeStore(store)
        self.store = store
        self.model = model
        self.sampling_params = sampling_params or SamplingParams()
        self.tool_schemas = tool_schemas or []
        self.trace_id = trace_id
        # Applied before an envelope is stored, so secrets never reach a fixture.
        self.redactors = redactors or []

    def _request_attributes(self) -> dict[str, AttributeValue]:
        return LLMRequest(
            model=self.model, sampling=self.sampling_params, tools=self.tool_schemas
        ).to_attributes()

    def record(
        self,
        node_id: str,
        input: Input,
        output: Output,
        *,
        trace_id: str | None = None,
        status: Status | None = None,
        attributes: dict[str, AttributeValue] | None = None,
    ) -> Envelope:
        envelope = Envelope(
            trace_id=trace_id or self.trace_id or new_trace_id(),
            name=node_id,
            input=input,
            output=output,
            status=status or Status(),
            attributes={**self._request_attributes(), **(attributes or {})},
        )
        if self.redactors:
            from chronicle.redaction import apply_redactors

            envelope = apply_redactors(envelope, self.redactors)
        if self.store is not None:
            self.store.append(envelope)
        return envelope

    def wrap_node(
        self,
        node_id: str,
        *,
        extract_input: Callable[[dict[str, Any]], Input] | None = None,
        extract_result: Callable[[dict[str, Any], Any], Output] | None = None,
    ) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """
        Decorator that records an envelope on every node invocation.

        Provide extract_input/extract_result to map framework-specific state
        into the canonical envelope schema.
        """

        def decorator(fn: Callable[P, R]) -> Callable[P, R]:
            def _prepare(args, kwargs):
                state = args[0] if args else kwargs.get("state", {})
                if not isinstance(state, dict):
                    state = {}
                if extract_input:
                    return state, extract_input(state)
                return state, Input(
                    arguments=state,
                    messages=[Message(**m) for m in state.get("messages", []) if isinstance(m, dict)],
                )

            def _on_success(state, input, result):
                if extract_result:
                    output = extract_result(state, result)
                else:
                    output = _default_extract_result(result)
                self.record(node_id, input, output)

            def _on_error(input, exc):
                self.record(
                    node_id, input, Output(),
                    status=Status(code="ERROR", message=str(exc)),
                    attributes={"error.type": type(exc).__name__},
                )

            if inspect.iscoroutinefunction(fn):
                @functools.wraps(fn)
                async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                    if not is_enabled():
                        return await fn(*args, **kwargs)
                    state, input = _prepare(args, kwargs)
                    try:
                        result = await fn(*args, **kwargs)
                    except Exception as exc:
                        _on_error(input, exc)
                        raise
                    _on_success(state, input, result)
                    return result

                return async_wrapper  # type: ignore[return-value]

            @functools.wraps(fn)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                if not is_enabled():
                    return fn(*args, **kwargs)
                state, input = _prepare(args, kwargs)
                try:
                    result = fn(*args, **kwargs)
                except Exception as exc:
                    _on_error(input, exc)
                    raise
                _on_success(state, input, result)
                return result

            return wrapper

        return decorator


def _default_extract_result(result: Any) -> Output:
    if isinstance(result, dict):
        tool_calls = [
            ToolCall(
                id=tc.get("id"),
                name=tc.get("name", ""),
                arguments=tc.get("arguments", tc.get("args", {})),
            )
            for tc in result.get("tool_calls", [])
        ]
        return Output(
            llm=LLMOutput(
                text=result.get("completion") or result.get("output"),
                tool_calls=tool_calls,
                finish_reason=result.get("finish_reason"),
                usage=usage_from(result.get("token_usage") or result.get("usage")),
            )
        )
    if isinstance(result, str):
        return Output(llm=LLMOutput(text=result))
    return Output(value=str(result))


def messages_to_input(
    messages: list[dict[str, Any]],
    *,
    arguments: dict[str, Any] | None = None,
) -> Input:
    return Input(
        arguments=arguments or {},
        messages=[Message(**m) for m in messages],
    )


def completion_to_output(
    text: str,
    *,
    tool_calls: list[ToolCall] | None = None,
    finish_reason: str | None = None,
    usage: Usage | None = None,
) -> Output:
    return Output(
        llm=LLMOutput(
            text=text,
            tool_calls=tool_calls or [],
            finish_reason=finish_reason,
            usage=usage,
        )
    )
