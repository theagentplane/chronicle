"""Chronicle runtime session: record, replay, and cut-point execution."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from chronicle.envelope.schema import (
    ActionResult,
    ContextMetadata,
    Envelope,
    InputState,
    SamplingParams,
    ToolCall,
    ToolSchema,
)
from chronicle.envelope.store import EnvelopeStore
from chronicle.replay.plan import ReplayPlan

if TYPE_CHECKING:
    from chronicle.execution_graph import ExecutionGraph

_envelope_stack: ContextVar[list[str]] = ContextVar("chronicle_envelope_stack", default=[])


class SessionMode(str, Enum):
    LIVE = "live"
    REPLAY = "replay"


@dataclass
class CallRecord:
    boundary_id: str
    invocation_index: int
    mode: str
    envelope_id: str | None = None


@dataclass
class ChronicleSession:
    mode: SessionMode = SessionMode.LIVE
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    store: EnvelopeStore | None = None
    replay_plan: ReplayPlan = field(default_factory=ReplayPlan)
    fixture_graph: ExecutionGraph | None = None  # type: ignore[name-defined]
    model_version: str = "unknown"
    build_id: str = field(default_factory=lambda: os.environ.get("CHRONICLE_BUILD_ID", "dev-local"))
    # Optional observer for boundary crossings (LIVE record + LIVE cut-point).
    # Signature: (boundary_id, kind, input_state, result) -> None
    on_crossing: Callable[[str, str, InputState, Any], None] | None = None
    # Applied to each envelope before it is retained or stored, so secrets never
    # reach a committed fixture. Empty by default; set to default_redactors() or
    # your own. Signature: (str) -> str. See chronicle.redaction.
    redactors: list[Callable[[str], str]] = field(default_factory=list)

    _sequence: int = 0
    _invocation_counts: dict[str, int] = field(default_factory=dict)
    _replay_cursor: dict[str, int] = field(default_factory=dict)
    _call_log: list[CallRecord] = field(default_factory=list)
    _captured_inputs: dict[tuple[str, int], InputState] = field(default_factory=dict)
    _captured_results: dict[tuple[str, int], Any] = field(default_factory=dict)
    _recorded_envelopes: list[Envelope] = field(default_factory=list)
    _last_envelope_id: str | None = None

    def begin_trace(self, trace_id: str | None = None) -> str:
        if trace_id:
            self.trace_id = trace_id
        else:
            self.trace_id = str(uuid.uuid4())
        self._sequence = 0
        self._invocation_counts.clear()
        self._replay_cursor.clear()
        self._call_log.clear()
        self._captured_inputs.clear()
        self._captured_results.clear()
        self._recorded_envelopes.clear()
        self._last_envelope_id = None
        _envelope_stack.set([])
        return self.trace_id

    def enable_replay(self, plan: ReplayPlan | None = None) -> None:
        self.mode = SessionMode.REPLAY
        self.replay_plan = plan or ReplayPlan()
        self._replay_cursor.clear()

    def enable_live(self) -> None:
        self.mode = SessionMode.LIVE
        self.fixture_graph = None

    def load_trace(self, path: str | Path) -> ExecutionGraph:
        from chronicle.execution_graph import ExecutionGraph

        self.fixture_graph = ExecutionGraph.load(path)
        self.trace_id = self.fixture_graph.trace_id
        self._replay_cursor.clear()
        return self.fixture_graph

    def current_parent_id(self) -> str | None:
        stack = _envelope_stack.get()
        return stack[-1] if stack else None

    def _push_envelope(self, envelope_id: str) -> None:
        stack = _envelope_stack.get().copy()
        stack.append(envelope_id)
        _envelope_stack.set(stack)

    def _pop_envelope(self) -> None:
        stack = _envelope_stack.get().copy()
        if stack:
            stack.pop()
        _envelope_stack.set(stack)

    def next_invocation(self, boundary_id: str) -> int:
        count = self._invocation_counts.get(boundary_id, 0) + 1
        self._invocation_counts[boundary_id] = count
        return count

    def next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def record_envelope(
        self,
        boundary_id: str,
        kind: str,
        input_state: InputState,
        action_result: ActionResult,
        *,
        model_version: str | None = None,
        sampling_params: SamplingParams | None = None,
        tool_schemas: list[ToolSchema] | None = None,
    ) -> Envelope:
        invocation_index = self.next_invocation(boundary_id)
        sequence = self.next_sequence()
        parent_id = self._last_envelope_id

        envelope = Envelope(
            trace_id=self.trace_id,
            node_id=boundary_id,
            boundary_kind=kind,
            parent_envelope_id=parent_id,
            sequence=sequence,
            invocation_index=invocation_index,
            metadata=ContextMetadata(
                # Prefer what the call actually used; fall back to the session
                # default only when the boundary surfaced no real metadata.
                model_version=model_version or self.model_version,
                build_id=self.build_id,
                sampling_params=sampling_params or SamplingParams(),
                tool_schemas=tool_schemas or [],
                framework="chronicle.boundary",
                node_id=boundary_id,
                trace_id=self.trace_id,
            ),
            input_state=input_state,
            action_result=action_result,
        )

        if self.redactors:
            from chronicle.redaction import apply_redactors

            envelope = apply_redactors(envelope, self.redactors)

        self._push_envelope(envelope.envelope_id)
        try:
            self._recorded_envelopes.append(envelope)
            self._last_envelope_id = envelope.envelope_id
            if self.store is not None:
                self.store.append(envelope)
        finally:
            self._pop_envelope()

        self._call_log.append(
            CallRecord(boundary_id, invocation_index, "record", envelope.envelope_id)
        )
        return envelope

    def _fixture_for(self, boundary_id: str) -> Envelope:
        if self.fixture_graph is None:
            raise RuntimeError("No fixture graph loaded — call load_trace() first")
        cursor = self._replay_cursor.get(boundary_id, 0) + 1
        self._replay_cursor[boundary_id] = cursor
        envelope = self.fixture_graph.envelope(boundary_id, cursor)
        self._call_log.append(
            CallRecord(boundary_id, cursor, "stub", envelope.envelope_id)
        )
        return envelope

    def stub_result(self, boundary_id: str, kind: str) -> Any:
        envelope = self._fixture_for(boundary_id)
        return envelope_to_return_value(envelope, kind)

    def capture_live_input(self, boundary_id: str, invocation_index: int, input_state: InputState) -> None:
        self._captured_inputs[(boundary_id, invocation_index)] = input_state

    def capture_live_result(self, boundary_id: str, invocation_index: int, result: Any) -> None:
        self._captured_results[(boundary_id, invocation_index)] = result
        self._call_log.append(
            CallRecord(boundary_id, invocation_index, "live", None)
        )

    def captured_input(self, boundary_id: str, invocation_index: int) -> InputState | None:
        return self._captured_inputs.get((boundary_id, invocation_index))

    def captured_result(self, boundary_id: str, invocation_index: int) -> Any:
        return self._captured_results.get((boundary_id, invocation_index))

    def invocation_count(self, boundary_id: str) -> int:
        return sum(1 for c in self._call_log if c.boundary_id == boundary_id)

    def call_log(self) -> list[CallRecord]:
        return list(self._call_log)

    def export_trace(self, directory: str | Path) -> Path:
        from chronicle.execution_graph import ExecutionGraph

        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        graph = ExecutionGraph.from_envelopes(self.trace_id, self._recorded_envelopes)
        graph.save(root)
        return root


# Context-scoped, not a plain global: concurrent async requests (and threads)
# each get their own session, so their traces never interleave. Boundaries within
# one request share the session set at that request's entry.
_session: ContextVar[ChronicleSession | None] = ContextVar("chronicle_session", default=None)


def get_session() -> ChronicleSession:
    session = _session.get()
    if session is None:
        session = ChronicleSession()
        _session.set(session)
    return session


def reset_session() -> ChronicleSession:
    session = ChronicleSession()
    _session.set(session)
    return session


def envelope_to_return_value(envelope: Envelope, kind: str) -> Any:
    if kind == "tool":
        raw = envelope.action_result.raw_response
        if raw is not None:
            return raw
        return {
            "status": envelope.action_result.completion or "ok",
            "blocked": False,
        }
    if kind == "llm":
        state = dict(envelope.input_state.graph_state)
        state["tool_calls"] = [tc.model_dump() for tc in envelope.action_result.tool_calls]
        state["completion"] = envelope.action_result.completion
        state["finish_reason"] = envelope.action_result.finish_reason
        return state
    raw = envelope.action_result.raw_response
    if raw is not None:
        return raw
    return envelope.action_result.completion


def result_to_action_result(result: Any, kind: str) -> ActionResult:
    if kind == "tool" and isinstance(result, dict):
        return ActionResult(
            completion=result.get("status", str(result)),
            raw_response=result,
        )
    if kind == "llm" and isinstance(result, dict):
        tool_calls = [
            ToolCall(
                id=tc.get("id"),
                name=tc.get("name", ""),
                arguments=tc.get("arguments", {}),
            )
            for tc in result.get("tool_calls", [])
        ]
        return ActionResult(
            tool_calls=tool_calls,
            completion=result.get("completion"),
            finish_reason=result.get("finish_reason"),
            token_usage=_as_token_usage(result.get("token_usage") or result.get("usage")),
        )
    return ActionResult(completion=str(result), raw_response=result if isinstance(result, dict) else None)


def _as_token_usage(source: Any) -> dict[str, int]:
    """Coerce a usage mapping into the envelope's ``dict[str, int]`` shape.

    LLM SDKs report usage under slightly different keys and occasionally as
    floats, so keep only the integer counts and drop anything else rather than
    fail validation on a stray value.
    """
    if not isinstance(source, Mapping):
        return {}
    usage: dict[str, int] = {}
    for key, value in source.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            usage[str(key)] = value
        elif isinstance(value, float) and value.is_integer():
            usage[str(key)] = int(value)
    return usage


def sampling_params_from(source: Any) -> SamplingParams | None:
    """Best-effort extraction of sampling parameters from a boundary result.

    Recognizes either a nested ``sampling_params`` mapping or the flat keys
    (temperature, top_p, max_tokens, seed) that common LLM SDKs return. Returns
    ``None`` when nothing recognizable is present, so callers fall back to the
    session/recorder default instead of recording empty parameters.
    """
    if not isinstance(source, Mapping):
        return None
    nested = source.get("sampling_params")
    if isinstance(nested, Mapping):
        source = nested
    keys = ("temperature", "top_p", "max_tokens", "seed")
    if not any(k in source for k in keys):
        return None
    return SamplingParams(
        temperature=source.get("temperature"),
        top_p=source.get("top_p"),
        max_tokens=source.get("max_tokens"),
        seed=source.get("seed"),
    )


def model_version_from(source: Any) -> str | None:
    """Best-effort extraction of the resolved model version from a result.

    Prefers an explicit ``model_version`` and falls back to ``model`` (what
    most SDK responses echo back). Returns ``None`` when neither is present.
    """
    if not isinstance(source, Mapping):
        return None
    value = source.get("model_version") or source.get("model")
    return str(value) if value else None
