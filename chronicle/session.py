"""Chronicle runtime session: record, replay, and cut-point execution."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
from chronicle.ids import new_span_id, new_trace_id, validate_trace_id
from chronicle.replay.plan import ReplayPlan

if TYPE_CHECKING:
    from chronicle.execution_graph import ExecutionGraph

_envelope_stack: ContextVar[list[str]] = ContextVar("chronicle_envelope_stack", default=[])
# Sentinel so record_envelope can accept parent_envelope_id=None for root spans.
_PARENT_UNSET = object()
# Dim carrying the human label of a trace (``record(name=...)``).
TRACE_NAME_DIM = "chronicle.trace.name"


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
    trace_id: str = field(default_factory=new_trace_id)
    store: EnvelopeStore | None = None
    replay_plan: ReplayPlan = field(default_factory=ReplayPlan)
    fixture_graph: ExecutionGraph | None = None  # type: ignore[name-defined]
    model_version: str = "unknown"
    build_id: str = field(default_factory=lambda: os.environ.get("CHRONICLE_BUILD_ID", "dev-local"))
    # Optional observer for boundary crossings (LIVE record + LIVE cut-point).
    # Signature: (boundary_id, kind, input_state, result) -> None
    on_crossing: Callable[[str, str, InputState, Any], None] | None = None
    # Optional pre-call hook (LIVE record + LIVE cut-point), after input capture
    # and before the wrapped function runs. May raise to abort (e.g. a governor
    # Halt). May return a mapping of kwargs to merge into the call (MUTATE).
    # Signature: (boundary_id, kind, input_state) -> Mapping[str, Any] | None
    on_enter: Callable[[str, str, InputState], Mapping[str, Any] | None] | None = None
    # Optional post-call cleanup (LIVE), always run after a successful on_enter
    # whether the function returned or raised. Signature:
    # (boundary_id, kind, input_state) -> None
    on_leave: Callable[[str, str, InputState], None] | None = None
    # Optional observer fired with the full Envelope right after it is recorded
    # (LIVE). Used by exporters (e.g. OpenTelemetry) to emit one span per crossing.
    # Signature: (envelope) -> None
    on_record: Callable[[Envelope], None] | None = None
    # Applied to each envelope before it is retained or stored, so secrets never
    # reach a committed fixture. Empty by default; set to default_redactors() or
    # your own. Signature: (str) -> str. See chronicle.redaction.
    redactors: list[Callable[[str], str]] = field(default_factory=list)
    # When False, envelopes are written to ``store`` only and not kept on the
    # session (``export_trace`` will be empty). Cuts memory traffic on hot paths.
    retain_envelopes: bool = True
    # Trace-level flat string→string attributes (copied onto every envelope).
    dims: dict[str, str] = field(default_factory=dict)

    _sequence: int = 0
    _invocation_counts: dict[str, int] = field(default_factory=dict)
    _replay_cursor: dict[str, int] = field(default_factory=dict)
    _call_log: list[CallRecord] = field(default_factory=list)
    _captured_inputs: dict[tuple[str, int], InputState] = field(default_factory=dict)
    _captured_results: dict[tuple[str, int], Any] = field(default_factory=dict)
    _recorded_envelopes: list[Envelope] = field(default_factory=list)
    _last_envelope_id: str | None = None
    _span_started_at: dict[str, datetime] = field(default_factory=dict)

    def begin_trace(
        self,
        name: str | None = None,
        *,
        trace_id: str | None = None,
        dims: dict[str, str] | None = None,
    ) -> str:
        """Start a new trace and return its id.

        ``name`` is a human label, stored as the ``chronicle.trace.name`` dim on every
        envelope. ``trace_id`` must be an OTel trace id (32 lowercase hex); omit it to
        mint one. The trace id itself is never free-form.
        """
        self.trace_id = validate_trace_id(trace_id) if trace_id else new_trace_id()
        if dims is not None:
            self.dims = {str(k): str(v) for k, v in dims.items()}
        if name:
            self.dims[TRACE_NAME_DIM] = name
        else:
            self.dims.pop(TRACE_NAME_DIM, None)
        self._sequence = 0
        self._invocation_counts.clear()
        self._replay_cursor.clear()
        self._call_log.clear()
        self._captured_inputs.clear()
        self._captured_results.clear()
        self._recorded_envelopes.clear()
        self._last_envelope_id = None
        self._span_started_at.clear()
        _envelope_stack.set([])
        return self.trace_id

    def start_span(self) -> tuple[str, str | None]:
        """Allocate a span id and push it as the active parent (OTel Context).

        Returns ``(span_id, parent_span_id)``. Nested boundaries that start while
        this span is active parent to ``span_id``. Call ``end_span`` in a finally.
        """
        parent_id = self.current_parent_id()
        span_id = new_span_id()
        self._span_started_at[span_id] = datetime.now(timezone.utc)
        self._push_envelope(span_id)
        return span_id, parent_id

    def end_span(self) -> None:
        """Pop the active span from the nest stack."""
        self._pop_envelope()

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
        envelope_id: str | None = None,
        parent_envelope_id: Any = _PARENT_UNSET,
        dims: dict[str, str] | None = None,
    ) -> Envelope:
        invocation_index = self.next_invocation(boundary_id)
        sequence = self.next_sequence()
        # Prefer explicit ids from start_span (OTel Context nesting). Fall back to
        # linear last-finished only when the caller did not open a span.
        # Important: parent_envelope_id=None means root (no parent); only the
        # sentinel means "compute parent for me".
        if envelope_id is None:
            envelope_id = new_span_id()
        if parent_envelope_id is _PARENT_UNSET:
            # If this id is already on the stack (start_span), parent is below it.
            stack = _envelope_stack.get()
            if stack and stack[-1] == envelope_id and len(stack) >= 2:
                parent_id = stack[-2]
            elif stack and stack[-1] != envelope_id:
                parent_id = stack[-1]
            else:
                parent_id = self._last_envelope_id
        else:
            parent_id = parent_envelope_id

        resolved_model = model_version or self.model_version
        # Trace dims first; envelope dims override. Promote common span attrs.
        merged_dims = {str(k): str(v) for k, v in self.dims.items()}
        if resolved_model and resolved_model != "unknown":
            merged_dims.setdefault("model_version", str(resolved_model))
        merged_dims.setdefault("boundary_kind", kind)
        merged_dims.setdefault("node_id", boundary_id)
        if dims:
            merged_dims.update({str(k): str(v) for k, v in dims.items()})

        # model_construct: fields are produced by Chronicle itself; skip pydantic
        # validation on the hot LIVE path.
        envelope = Envelope.model_construct(
            schema_version="1.0",
            envelope_id=envelope_id,
            trace_id=self.trace_id,
            node_id=boundary_id,
            boundary_kind=kind,
            parent_envelope_id=parent_id,
            sequence=sequence,
            invocation_index=invocation_index,
            timestamp=datetime.now(timezone.utc),
            started_at=self._span_started_at.pop(envelope_id, None),
            metadata=ContextMetadata.model_construct(
                # Prefer what the call actually used; fall back to the session
                # default only when the boundary surfaced no real metadata.
                model_version=resolved_model,
                build_id=self.build_id,
                sampling_params=sampling_params or SamplingParams.model_construct(
                    temperature=None, top_p=None, max_tokens=None, seed=None, extra={},
                ),
                tool_schemas=tool_schemas or [],
                framework="chronicle.boundary",
                extra={},
            ),
            input_state=input_state,
            action_result=action_result,
            dims=merged_dims,
        )

        if self.redactors:
            from chronicle.redaction import apply_redactors

            envelope = apply_redactors(envelope, self.redactors)

        if self.retain_envelopes:
            self._recorded_envelopes.append(envelope)
        self._last_envelope_id = envelope.envelope_id
        if self.store is not None:
            self.store.append(envelope)

        self._call_log.append(
            CallRecord(boundary_id, invocation_index, "record", envelope.envelope_id)
        )
        if self.on_record is not None:
            self.on_record(envelope)
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

    @property
    def envelopes(self) -> list[Envelope]:
        """Recorded envelopes for this trace (empty when ``retain_envelopes=False``)."""
        return list(self._recorded_envelopes)

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


def peek_session() -> ChronicleSession | None:
    """Return the context session if one exists, without creating one."""
    return _session.get()


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
    if kind == "router":
        # A router's return value is a plain node-name (or list of names), not a
        # dict, so it lives inside raw_response under a fixed key rather than
        # being raw_response itself — the generic dict-passthrough below would
        # otherwise hand back {"decision": ...} instead of the decision itself.
        raw = envelope.action_result.raw_response
        if raw is not None and "decision" in raw:
            return raw["decision"]
        return envelope.action_result.completion
    raw = envelope.action_result.raw_response
    if raw is not None:
        return raw
    return envelope.action_result.completion


def _router_decision(result: Any) -> Any:
    """Coerce a routing function's return value into a JSON-safe, faithfully
    replayable shape. LangGraph routing functions return a node name or a list
    of node names (``Hashable | list[Hashable]``); node names are strings in
    practice (``END`` included), so this covers the real range without needing
    general-purpose JSON coercion."""
    if isinstance(result, str):
        return result
    if isinstance(result, (list, tuple)):
        return [str(v) for v in result]
    return str(result)


def result_to_action_result(result: Any, kind: str) -> ActionResult:
    if kind == "tool" and isinstance(result, dict):
        return ActionResult.model_construct(
            tool_calls=[],
            completion=result.get("status", str(result)),
            finish_reason=None,
            token_usage={},
            raw_response=result,
            error=None,
            error_type=None,
        )
    if kind == "router":
        decision = _router_decision(result)
        return ActionResult(
            completion=decision if isinstance(decision, str) else str(decision),
            raw_response={"decision": decision},
        )
    if kind == "llm" and isinstance(result, dict):
        tool_calls = [
            ToolCall.model_construct(
                id=tc.get("id"),
                name=tc.get("name", ""),
                arguments=tc.get("arguments", {}),
            )
            for tc in result.get("tool_calls", [])
        ]
        return ActionResult.model_construct(
            tool_calls=tool_calls,
            completion=result.get("completion"),
            finish_reason=result.get("finish_reason"),
            token_usage=_as_token_usage(result.get("token_usage") or result.get("usage")),
            raw_response=None,
            error=None,
            error_type=None,
        )
    return ActionResult.model_construct(
        tool_calls=[],
        completion=str(result),
        finish_reason=None,
        token_usage={},
        raw_response=result if isinstance(result, dict) else None,
        error=None,
        error_type=None,
    )


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
