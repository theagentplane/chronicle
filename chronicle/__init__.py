"""Chronicle: Agent Data Recorder and Verification Test Bench."""

from chronicle.api import record, replay_trace
from chronicle.boundary import boundary, wrap_llm
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
from chronicle.envelope.backends import (
    JsonlStore,
    RemoteStore,
    SqliteStore,
    Store,
    open_store,
)
from chronicle.envelope.store import EnvelopeStore
from chronicle.execution_graph import ExecutionGraph
from chronicle.redaction import apply_redactors, default_redactors, redact_secrets
from chronicle.replay.plan import BoundaryMode, ReplayPlan
from chronicle.session import ChronicleSession, SessionMode, get_session, reset_session
from chronicle.wrap import instrument_langgraph, wrap

__version__ = "0.3.0"


def __getattr__(name: str):
    # Lazy so the base install never imports opentelemetry. `chronicle.instrument_otel`
    # (and the attribute mapper) load the optional OTel export on first access.
    if name in ("instrument_otel", "envelope_span_attributes"):
        from chronicle import otel

        return getattr(otel, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ActionResult",
    "BoundaryMode",
    "ChronicleSession",
    "ContextMetadata",
    "Envelope",
    "EnvelopeStore",
    "ExecutionGraph",
    "InputState",
    "JsonlStore",
    "RagChunk",
    "RemoteStore",
    "ReplayPlan",
    "SamplingParams",
    "SessionMode",
    "SqliteStore",
    "Store",
    "ToolCall",
    "ToolSchema",
    "apply_redactors",
    "boundary",
    "default_redactors",
    "envelope_span_attributes",
    "get_session",
    "instrument_langgraph",
    "instrument_otel",
    "open_store",
    "record",
    "redact_secrets",
    "replay_trace",
    "reset_session",
    "wrap",
    "wrap_llm",
]
