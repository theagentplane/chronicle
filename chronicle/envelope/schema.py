"""Immutable envelope schema for graph-boundary agent execution records."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator

from chronicle.ids import new_span_id, new_trace_id, validate_span_id, validate_trace_id


class SamplingParams(BaseModel):
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    seed: int | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ToolSchema(BaseModel):
    name: str
    description: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class ContextMetadata(BaseModel):
    """Pinned runtime context — model version must be resolved, not an alias."""

    model_version: str
    sampling_params: SamplingParams = Field(default_factory=SamplingParams)
    build_id: str
    tool_schemas: list[ToolSchema] = Field(default_factory=list)
    framework: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class RagChunk(BaseModel):
    chunk_id: str
    content: str
    source: str | None = None
    score: float | None = None
    index_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class InputState(BaseModel):
    """Full assembled prompt and retrieved context at the graph boundary."""

    messages: list[dict[str, Any]]
    system_prompt: str | None = None
    rag_chunks: list[RagChunk] = Field(default_factory=list)
    graph_state: dict[str, Any] = Field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        payload = json.dumps(
            {
                "messages": self.messages,
                "system_prompt": self.system_prompt,
                "rag_chunks": [c.model_dump() for c in self.rag_chunks],
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


class ToolCall(BaseModel):
    id: str | None = None
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ActionResult(BaseModel):
    """Structured tool calls and model completion emitted at this boundary."""

    tool_calls: list[ToolCall] = Field(default_factory=list)
    completion: str | None = None
    finish_reason: str | None = None
    token_usage: dict[str, int] = Field(default_factory=dict)
    raw_response: dict[str, Any] | None = None
    # Set when the boundary raised. Optional and default None, so pre-0.2
    # envelopes still load unchanged.
    error: str | None = None
    error_type: str | None = None


class Envelope(BaseModel):
    """
    Immutable, append-only record of a single graph-boundary execution.

    Every envelope captures contextual metadata, input state, and action/result
    at the intersection of agent nodes — the "flight data" of the agent.

    OTel mapping: ``trace_id`` is the OTel trace id (32 lowercase hex chars);
    ``envelope_id`` is the span id (16 lowercase hex chars); ``parent_envelope_id``
    is ``parent_span_id``. Both are validated to OTel's byte formats, so an envelope
    exports as a span without translating ids. ``dims`` are flat string attributes
    (trace-level dims are copied onto every span at record time; envelope-level
    dims are span-specific). Read-only OTel-named getters: ``span_id``,
    ``parent_span_id``, ``name``, ``start_time``, ``end_time``, ``attributes``.
    """

    schema_version: str = "1.0"
    envelope_id: str = Field(default_factory=new_span_id)
    trace_id: str = Field(default_factory=new_trace_id)
    node_id: str
    boundary_kind: str = "custom"
    parent_envelope_id: str | None = None
    sequence: int = 0
    invocation_index: int = 1
    # End time (when the envelope was written). Prefer ``started_at`` for span start.
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # Span start (OTel). None on pre-nest fixtures; waterfall falls back to timestamp.
    started_at: datetime | None = None
    metadata: ContextMetadata
    input_state: InputState
    action_result: ActionResult
    # Flat string→string attributes (OTel-style). Missing on pre-0.4 fixtures.
    dims: dict[str, str] = Field(default_factory=dict)

    @property
    def boundary_id(self) -> str:
        return self.node_id

    @property
    def span_id(self) -> str:
        """OTel alias for ``envelope_id``."""
        return self.envelope_id

    @property
    def parent_span_id(self) -> str | None:
        """OTel alias for ``parent_envelope_id``."""
        return self.parent_envelope_id

    @property
    def name(self) -> str:
        """OTel span name: the id of the boundary that produced this envelope."""
        return self.node_id

    @property
    def start_time(self) -> datetime:
        """OTel span start. Falls back to ``timestamp`` on pre-nest fixtures."""
        return self.started_at or self.timestamp

    @property
    def end_time(self) -> datetime:
        """OTel span end (alias for ``timestamp``)."""
        return self.timestamp

    @property
    def attributes(self) -> dict[str, str]:
        """OTel span attributes (alias for ``dims``)."""
        return self.dims

    @field_validator("trace_id")
    @classmethod
    def _check_trace_id(cls, v: str) -> str:
        return validate_trace_id(v)

    @field_validator("envelope_id")
    @classmethod
    def _check_envelope_id(cls, v: str) -> str:
        return validate_span_id(v)

    @field_validator("parent_envelope_id")
    @classmethod
    def _check_parent_envelope_id(cls, v: str | None) -> str | None:
        return None if v is None else validate_span_id(v)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _ensure_utc(cls, v: datetime | str) -> datetime:
        if isinstance(v, str):
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    def to_json(self, *, indent: int | None = 2) -> str:
        return self.model_dump_json(indent=indent)

    @classmethod
    def from_json(cls, data: str | bytes) -> Envelope:
        return cls.model_validate_json(data)

    @classmethod
    def from_file(cls, path: str) -> Envelope:
        with open(path, encoding="utf-8") as f:
            return cls.from_json(f.read())

    def write_file(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())

    @staticmethod
    def json_schema() -> dict[str, Any]:
        return Envelope.model_json_schema()
