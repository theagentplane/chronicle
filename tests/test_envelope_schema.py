"""Tests for the Envelope schema."""

import json
from pathlib import Path

import pytest

from chronicle import Envelope, Input, Output
from chronicle.envelope.schema import rag_chunks_from
from chronicle.envelope.store import EnvelopeStore


FIXTURES = Path(__file__).parent.parent / "fixtures" / "envelopes"


def test_envelope_round_trip():
    envelope = Envelope.from_file(str(FIXTURES / "support-agent-001.json"))
    restored = Envelope.from_json(envelope.to_json())
    assert restored.envelope_id == envelope.envelope_id
    assert restored.model == "stub-support-model-1"
    assert [t.name for t in restored.tool_schemas] == ["search_docs"]
    assert len(rag_chunks_from(restored.input.arguments)) == 1


def test_envelope_has_no_metadata_object():
    """Model, sampling and tool definitions are span attributes, not a nested object."""
    assert "metadata" not in Envelope.model_fields
    envelope = Envelope.from_file(str(FIXTURES / "support-agent-001.json"))
    assert envelope.attributes["gen_ai.request.model"] == envelope.model
    assert envelope.attributes["gen_ai.request.temperature"] == 0.0
    assert envelope.attributes["gen_ai.request.seed"] == 42


def test_input_and_output_shapes():
    assert list(Input.model_fields) == ["arguments", "messages"]
    assert list(Output.model_fields) == ["value", "llm"]


def test_json_schema_export():
    schema = Envelope.json_schema()
    assert schema["title"] == "Envelope"
    assert {"input", "output", "attributes", "status"} <= set(schema["properties"])


def test_envelope_store_append_and_query(tmp_path):
    store = EnvelopeStore(tmp_path / "envelopes.jsonl")
    envelope = Envelope.from_file(str(FIXTURES / "support-agent-001.json"))
    store.append(envelope)
    found = store.find_by_trace_id(envelope.trace_id)
    assert len(found) == 1
    assert found[0].name == "agent"


def test_export_trace(tmp_path):
    store = EnvelopeStore(tmp_path / "envelopes.jsonl")
    envelope = Envelope.from_file(str(FIXTURES / "support-agent-001.json"))
    store.append(envelope)
    paths = store.export_trace(envelope.trace_id, tmp_path / "fixtures")
    assert len(paths) == 1
    assert json.loads(paths[0].read_text())["envelope_id"] == envelope.envelope_id
