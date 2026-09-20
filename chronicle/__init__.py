"""Chronicle: Agent Data Recorder and Verification Test Bench."""

from chronicle.api import record, replay_trace
from chronicle.boundary import boundary, wrap_llm
from chronicle.config import is_enabled
from chronicle.envelope.schema import (
    Envelope,
    Input,
    LLMOutput,
    Message,
    Output,
    RagChunk,
    Status,
    ToolCall,
    Usage,
)
from chronicle.envelope.genai import LLMRequest, SamplingParams, ToolSchema
from chronicle.envelope.backends import (
    BufferedStore,
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
from chronicle.wrap import instrument, instrument_langgraph, wrap

__version__ = "0.4.0"


def __getattr__(name: str):
    # Lazy so the base install never imports opentelemetry. `chronicle.instrument_otel`
    # (and the attribute mapper) load the optional OTel export on first access.
    if name in ("instrument_otel", "envelope_span_attributes"):
        from chronicle import otel

        return getattr(otel, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BoundaryMode",
    "BufferedStore",
    "ChronicleSession",
    "Envelope",
    "EnvelopeStore",
    "ExecutionGraph",
    "Input",
    "JsonlStore",
    "LLMOutput",
    "LLMRequest",
    "Message",
    "Output",
    "RagChunk",
    "RemoteStore",
    "ReplayPlan",
    "SamplingParams",
    "SessionMode",
    "SqliteStore",
    "Status",
    "Store",
    "ToolCall",
    "ToolSchema",
    "Usage",
    "apply_redactors",
    "boundary",
    "default_redactors",
    "envelope_span_attributes",
    "get_session",
    "instrument",
    "instrument_langgraph",
    "instrument_otel",
    "is_enabled",
    "open_store",
    "record",
    "redact_secrets",
    "replay_trace",
    "reset_session",
    "wrap",
    "wrap_llm",
]
