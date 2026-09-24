"""Chronicle runtime session: record, replay, and cut-point execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from chronicle.envelope.genai import GEN_AI_REQUEST_MODEL, AttributeValue
from chronicle.envelope.schema import (
    Envelope,
    Input,
    LLMOutput,
    Output,
    Status,
    ToolCall,
    Usage,
)
from chronicle.envelope.store import EnvelopeStore
from chronicle.ids import new_span_id, new_trace_id, validate_trace_id
from chronicle.replay.plan import ReplayPlan

if TYPE_CHECKING:
    from chronicle.execution_graph import ExecutionGraph

_envelope_stack: ContextVar[list[str]] = ContextVar("chronicle_envelope_stack", default=[])
# Sentinel so record_envelope can accept parent_envelope_id=None for root spans.
_PARENT_UNSET = object()
# Attribute carrying the human label of a trace (``record(name=...)``).
TRACE_NAME_ATTR = "chronicle.trace.name"


class SessionMode(str, Enum):
    LIVE = "live"
    REPLAY = "replay"


@dataclass
class CallRecord:
    name: str
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
    # Default model for LLM boundaries that do not surface their own.
    model: str | None = None
    # Optional observer for boundary crossings (LIVE record + LIVE cut-point).
    # Signature: (name, kind, input, result) -> None
    on_crossing: Callable[[str, str, Input, Any], None] | None = None
    # Optional pre-call hook (LIVE record + LIVE cut-point), after input capture
    # and before the wrapped function runs. May raise to abort (e.g. a governor
    # Halt). May return a mapping of kwargs to merge into the call (MUTATE).
    # Signature: (name, kind, input) -> Mapping[str, Any] | None
    on_enter: Callable[[str, str, Input], Mapping[str, Any] | None] | None = None
    # Optional post-call cleanup (LIVE), always run after a successful on_enter
    # whether the function returned or raised. Signature:
    # (name, kind, input) -> None
    on_leave: Callable[[str, str, Input], None] | None = None
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
    attributes: dict[str, AttributeValue] = field(default_factory=dict)

    _sequence: int = 0
    _invocation_counts: dict[str, int] = field(default_factory=dict)
    _replay_cursor: dict[str, int] = field(default_factory=dict)
    _call_log: list[CallRecord] = field(default_factory=list)
    _captured_inputs: dict[tuple[str, int], Input] = field(default_factory=dict)
    _captured_results: dict[tuple[str, int], Any] = field(default_factory=dict)
    _recorded_envelopes: list[Envelope] = field(default_factory=list)
    _last_envelope_id: str | None = None
    _span_started_at: dict[str, datetime] = field(default_factory=dict)

    def begin_trace(
        self,
        name: str | None = None,
        *,
        trace_id: str | None = None,
        attributes: dict[str, AttributeValue] | None = None,
    ) -> str:
        """Start a new trace and return its id.

        ``name`` is a human label, stored as the ``chronicle.trace.name`` attribute on every
        envelope. ``trace_id`` must be an OTel trace id (32 lowercase hex); omit it to
        mint one. The trace id itself is never free-form.
        """
        self.trace_id = validate_trace_id(trace_id) if trace_id else new_trace_id()
        if attributes is not None:
            self.attributes = {str(k): _attribute(v) for k, v in attributes.items()}
        if name:
            self.attributes[TRACE_NAME_ATTR] = name
        else:
            self.attributes.pop(TRACE_NAME_ATTR, None)
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

    def next_invocation(self, name: str) -> int:
        count = self._invocation_counts.get(name, 0) + 1
        self._invocation_counts[name] = count
        return count

    def next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def record_envelope(
        self,
        name: str,
        kind: str,
        input: Input,
        output: Output,
        *,
        envelope_id: str | None = None,
        parent_envelope_id: Any = _PARENT_UNSET,
        status: Status | None = None,
        attributes: dict[str, AttributeValue] | None = None,
    ) -> Envelope:
        invocation_index = self.next_invocation(name)
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

        # Trace attributes first; envelope attributes override.
        merged_attrs = dict(self.attributes)
        if attributes:
            merged_attrs.update(attributes)
        if kind == "llm" and self.model:
            merged_attrs.setdefault(GEN_AI_REQUEST_MODEL, self.model)

        # model_construct: fields are produced by Chronicle itself; skip pydantic
        # validation on the hot LIVE path.
        envelope = Envelope.model_construct(
            schema_version="2.0",
            envelope_id=envelope_id,
            trace_id=self.trace_id,
            name=name,
            kind=kind,
            parent_envelope_id=parent_id,
            sequence=sequence,
            invocation_index=invocation_index,
            start_time=self._span_started_at.pop(envelope_id, None),
            end_time=datetime.now(timezone.utc),
            status=status or Status(),
            input=input,
            output=output,
            attributes=merged_attrs,
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
            CallRecord(name, invocation_index, "record", envelope.envelope_id)
        )
        if self.on_record is not None:
            self.on_record(envelope)
        return envelope

    def _fixture_for(self, name: str) -> Envelope:
        if self.fixture_graph is None:
            raise RuntimeError("No fixture graph loaded — call load_trace() first")
        cursor = self._replay_cursor.get(name, 0) + 1
        self._replay_cursor[name] = cursor
        envelope = self.fixture_graph.envelope(name, cursor)
        self._call_log.append(
            CallRecord(name, cursor, "stub", envelope.envelope_id)
        )
        return envelope

    def stub_result(self, name: str, kind: str) -> Any:
        envelope = self._fixture_for(name)
        return envelope_to_return_value(envelope, kind)

    def capture_live_input(self, name: str, invocation_index: int, input: Input) -> None:
        self._captured_inputs[(name, invocation_index)] = input

    def capture_live_result(self, name: str, invocation_index: int, result: Any) -> None:
        self._captured_results[(name, invocation_index)] = result
        self._call_log.append(
            CallRecord(name, invocation_index, "live", None)
        )

    def captured_input(self, name: str, invocation_index: int) -> Input | None:
        return self._captured_inputs.get((name, invocation_index))

    def captured_result(self, name: str, invocation_index: int) -> Any:
        return self._captured_results.get((name, invocation_index))

    def invocation_count(self, name: str) -> int:
        return sum(1 for c in self._call_log if c.name == name)

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
    """What a stubbed boundary returns to its caller on replay."""
    if kind == "tool":
        value = envelope.output.value
        return value if value is not None else {"status": "ok", "blocked": False}
    if kind == "llm":
        llm = envelope.output.llm or LLMOutput()
        state = dict(envelope.input.arguments)
        state["tool_calls"] = [tc.model_dump() for tc in llm.tool_calls]
        state["completion"] = llm.text
        state["finish_reason"] = llm.finish_reason
        return state
    if kind == "router":
        # A router's return value is a plain node-name (or list of names), not a
        # dict, so it lives inside ``value`` under a fixed key rather than being the
        # value itself: the generic passthrough below would otherwise hand back
        # {"decision": ...} instead of the decision.
        value = envelope.output.value
        if isinstance(value, dict) and "decision" in value:
            return value["decision"]
        return value
    return envelope.output.value


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


def result_to_output(result: Any, kind: str) -> Output:
    if kind == "router":
        return Output(value={"decision": _router_decision(result)})
    if kind == "llm" and isinstance(result, dict):
        tool_calls = [
            ToolCall.model_construct(
                id=tc.get("id"),
                name=tc.get("name", ""),
                arguments=tc.get("arguments", {}),
            )
            for tc in result.get("tool_calls", [])
        ]
        return Output.model_construct(
            value=None,
            llm=LLMOutput.model_construct(
                text=result.get("completion"),
                tool_calls=tool_calls,
                finish_reason=result.get("finish_reason"),
                usage=usage_from(result.get("token_usage") or result.get("usage")),
            ),
        )
    return Output.model_construct(value=_value(result), llm=None)


def _value(result: Any) -> Any:
    """A return value the envelope can always serialize: dicts and primitives as-is,
    anything else as its string form."""
    if result is None or isinstance(result, (dict, str, bool, int, float)):
        return result
    return str(result)


def usage_from(source: Any) -> Usage | None:
    """Normalize a provider usage payload (mapping or SDK object) into :class:`Usage`.

    Providers name the counts differently (``prompt_tokens`` / ``input_tokens``,
    ``completion_tokens`` / ``output_tokens``) and occasionally return floats; only
    integral counts are kept. Returns ``None`` when there is nothing to record.
    """
    if source is not None and not isinstance(source, Mapping) and hasattr(source, "model_dump"):
        try:
            source = source.model_dump()
        except Exception:
            return None
    if not isinstance(source, Mapping):
        return None

    def count(*keys: str) -> int | None:
        for key in keys:
            value = source.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, int):
                return value
            if isinstance(value, float) and value.is_integer():
                return int(value)
        return None

    input_tokens = count("input_tokens", "prompt_tokens", "inputTokens", "promptTokenCount")
    output_tokens = count("output_tokens", "completion_tokens", "outputTokens", "candidatesTokenCount")
    if input_tokens is None and output_tokens is None:
        return None
    return Usage(input_tokens=input_tokens, output_tokens=output_tokens)


def _attribute(value: Any) -> AttributeValue:
    """Keep OTel-legal attribute values as they are; stringify anything else."""
    if isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)) and value and all(
        isinstance(v, type(value[0])) and isinstance(v, (str, bool, int, float)) for v in value
    ):
        return list(value)
    return str(value)
