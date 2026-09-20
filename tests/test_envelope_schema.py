"""Tests for the Envelope schema."""

import json
from pathlib import Path

import pytest

from chronicle import Envelope, Input, Metadata
from chronicle.envelope.store import EnvelopeStore


FIXTURES = Path(__file__).parent.parent / "fixtures" / "envelopes"


def test_envelope_round_trip():
    envelope = Envelope.from_file(str(FIXTURES / "support-agent-001.json"))
    restored = Envelope.from_json(envelope.to_json())
    assert restored.envelope_id == envelope.envelope_id
    assert restored.metadata.model == "stub-support-model-1"
    assert len(restored.input.rag_chunks) == 1


def test_metadata_holds_only_model_sampling_and_tool_schemas():
    assert list(Metadata.model_fields) == ["model", "sampling_params", "tool_schemas"]
    assert not hasattr(Input(messages=[]), "content_hash")


def test_json_schema_export():
    schema = Envelope.json_schema()
    assert schema["title"] == "Envelope"
    assert "metadata" in schema["properties"]


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
