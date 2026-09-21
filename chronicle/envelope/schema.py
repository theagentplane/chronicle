"""Immutable envelope schema for graph-boundary agent execution records."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from chronicle.envelope.genai import (
    CHRONICLE_INPUT_SCHEMA,
    CHRONICLE_OUTPUT_SCHEMA,
    GEN_AI_REQUEST_MODEL,
    AttributeValue,
)
from chronicle.ids import new_span_id, new_trace_id, validate_span_id, validate_trace_id


class Envelope(BaseModel):
    """
    Immutable, append-only record of a single graph-boundary execution.

    Every envelope captures the boundary's input, its output and its span attributes at
    the intersection of agent nodes — the "flight data" of the agent.

    OTel mapping: ``trace_id`` is the OTel trace id (32 lowercase hex chars);
    ``envelope_id`` is the span id (16 lowercase hex chars); ``parent_envelope_id``
    is ``parent_span_id``. Both are validated to OTel's byte formats, so an envelope
    exports as a span without translating ids. Other span fields use OTel names:
    ``name`` (the boundary name), ``kind`` (llm / tool / router / custom),
    ``start_time`` / ``end_time``, ``status`` and ``attributes`` (trace-level ones are
    copied onto every span at record time, envelope-level ones are span-specific).
    ``span_id`` and ``parent_span_id`` are read-only getters for ``envelope_id`` and
    ``parent_envelope_id``; ``model`` reads the GenAI attributes.
    """

    schema_version: str = "2.0"
    envelope_id: str = Field(default_factory=new_span_id)
    trace_id: str = Field(default_factory=new_trace_id)
    name: str
    kind: str = "custom"
    parent_envelope_id: str | None = None
    sequence: int = 0
    invocation_index: int = 1
    # Span start (OTel). None when no span was opened; the waterfall falls back to end_time.
    start_time: datetime | None = None
    # Span end: when the envelope was written.
    end_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: Status = Field(default_factory=lambda: Status())
    input: Input
    output: Output
    # OTel span attributes: primitives or lists of primitives. Model, sampling and tool
    # definitions live here under the GenAI semantic-convention keys.
    attributes: dict[str, AttributeValue] = Field(default_factory=dict)

    @property
    def span_id(self) -> str:
        """OTel alias for ``envelope_id``."""
        return self.envelope_id

    @property
    def parent_span_id(self) -> str | None:
        """OTel alias for ``parent_envelope_id``."""
        return self.parent_envelope_id

    @property
    def model(self) -> str | None:
        """The model this call ran with (``gen_ai.request.model``), if recorded."""
        value = self.attributes.get(GEN_AI_REQUEST_MODEL)
        return value if isinstance(value, str) else None

    @property
    def input_schema(self) -> dict[str, Any] | None:
        """JSON schema of the boundary method's input, for method boundaries."""
        return _json_attribute(self.attributes.get(CHRONICLE_INPUT_SCHEMA))

    @property
    def output_schema(self) -> dict[str, Any] | None:
        """JSON schema of the boundary method's return type, when it is annotated."""
        return _json_attribute(self.attributes.get(CHRONICLE_OUTPUT_SCHEMA))

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

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def _ensure_utc(cls, v: datetime | str | None) -> datetime | None:
        if v is None:
            return None
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


class Status(BaseModel):
    """OTel span status. ``UNSET`` by default; ``ERROR`` (with a message) when the
    boundary raised. The exception class goes in the ``error.type`` attribute."""

    code: Literal["UNSET", "OK", "ERROR"] = "UNSET"
    message: str | None = None


class Input(BaseModel):
    """What the boundary was called with.

    ``arguments`` is the annotated method's (or wrapped call's) arguments by name: the
    single source of truth that replay and assertions read. ``messages`` is the typed
    chat view, filled for LLM boundaries only.
    """

    arguments: dict[str, Any] = Field(default_factory=dict)
    messages: list[Message] = Field(default_factory=list)


class Message(BaseModel):
    """One chat message. Extra provider fields (``name``, ``tool_call_id`` ...) are kept."""

    model_config = ConfigDict(extra="allow")

    role: str
    content: Any = None


class Output(BaseModel):
    """What the boundary returned.

    ``value`` is the JSON-safe return value (what replay hands back for tools, routers and
    custom boundaries). ``llm`` bundles the normalized LLM response and is set for LLM
    boundaries only.
    """

    value: Any = None
    llm: LLMOutput | None = None


class LLMOutput(BaseModel):
    """The LLM-shaped view of a response, whatever provider produced it."""

    text: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str | None = None
    usage: Usage | None = None


class ToolCall(BaseModel):
    id: str | None = None
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Usage(BaseModel):
    """Normalized token counts (providers report these under different keys)."""

    input_tokens: int | None = None
    output_tokens: int | None = None


class RagChunk(BaseModel):
    """One retrieved passage. Not stored on the envelope itself: read a call's chunks
    back out of ``Input.arguments`` with :func:`rag_chunks_from`."""

    chunk_id: str
    content: str
    source: str | None = None
    score: float | None = None
    index_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def rag_chunks_from(arguments: Mapping[str, Any]) -> list[RagChunk]:
    """Retrieved chunks from a call's arguments (``rag_chunks`` or ``context``), or ``[]``."""
    out: list[RagChunk] = []
    for chunk in arguments.get("rag_chunks") or arguments.get("context") or []:
        if isinstance(chunk, RagChunk):
            out.append(chunk)
        elif isinstance(chunk, Mapping) and "chunk_id" in chunk and "content" in chunk:
            out.append(RagChunk(**chunk))
        elif isinstance(chunk, str):
            out.append(RagChunk(chunk_id=str(len(out)), content=chunk))
    return out


def _json_attribute(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, str):
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None
