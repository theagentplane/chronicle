"""Tool schemas: a tool boundary's schema is inferred from the wrapped method, and an
LLM boundary records the tools it was given. Both land in span attributes."""

from __future__ import annotations

import json
from typing import Literal

import chronicle
from chronicle import boundary
from chronicle.envelope.genai import (
    GEN_AI_TOOL_DEFINITIONS,
    GEN_AI_TOOL_DESCRIPTION,
    GEN_AI_TOOL_NAME,
    ToolSchema,
    infer_tool_schema,
    tool_schemas_from,
)

OPENAI = {
    "type": "function",
    "function": {
        "name": "search_docs",
        "description": "Search docs",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
    },
}
ANTHROPIC = {
    "name": "get_weather",
    "description": "Weather",
    "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
}
PLAIN = {"name": "add", "description": "Add", "parameters": {"type": "object"}}


def test_infer_tool_schema_from_signature_and_docstring():
    def delete_file(path: str, force: bool = False, mode: Literal["soft", "hard"] = "soft"):
        """Delete a file.

        Longer details that are not part of the description.
        """

    schema = infer_tool_schema(delete_file, "delete_file")
    assert schema.name == "delete_file"
    assert schema.description == "Delete a file."
    assert schema.parameters["type"] == "object"
    assert schema.parameters["required"] == ["path"]
    assert schema.parameters["properties"]["path"] == {"type": "string"}
    assert schema.parameters["properties"]["force"]["type"] == "boolean"
    assert schema.parameters["properties"]["mode"]["enum"] == ["soft", "hard"]
    assert "additionalProperties" not in schema.parameters


def test_infer_tool_schema_never_raises():
    class Opaque:
        pass

    def weird(x: Opaque):  # not JSON-schematizable
        return x

    schema = infer_tool_schema(weird, "weird")
    assert schema.name == "weird"
    assert schema.parameters["type"] == "object"


def test_tool_boundary_records_its_own_inferred_schema():
    @boundary("delete_file", kind="tool")
    def delete_file(path: str, force: bool = False) -> dict:
        """Delete a file from disk."""
        return {"status": "deleted", "path": path}

    with chronicle.record("t") as session:
        delete_file("/tmp/x")
    (env,) = session.envelopes
    assert env.attributes[GEN_AI_TOOL_NAME] == "delete_file"
    assert env.attributes[GEN_AI_TOOL_DESCRIPTION] == "Delete a file from disk."
    (schema,) = env.tool_schemas
    assert schema.parameters["required"] == ["path"]
    assert json.loads(env.attributes[GEN_AI_TOOL_DEFINITIONS])[0]["name"] == "delete_file"


def test_failed_tool_boundary_still_records_its_schema():
    @boundary("boom", kind="tool")
    def boom(x: int):
        """Always fails."""
        raise RuntimeError("no")

    with chronicle.record("t") as session:
        try:
            boom(1)
        except RuntimeError:
            pass
    (env,) = session.envelopes
    assert env.attributes[GEN_AI_TOOL_NAME] == "boom"
    assert env.attributes["error.type"] == "RuntimeError"


def test_tool_schemas_from_normalizes_the_common_shapes():
    schemas = tool_schemas_from({"tools": [OPENAI, ANTHROPIC, PLAIN]})
    assert [s.name for s in schemas] == ["search_docs", "get_weather", "add"]
    assert schemas[0].parameters["properties"]["query"] == {"type": "string"}
    assert schemas[1].parameters["properties"]["city"] == {"type": "string"}
    assert schemas[2].description == "Add"


def test_tool_schemas_from_returns_none_when_absent():
    assert tool_schemas_from({}) is None
    assert tool_schemas_from({"tools": []}) is None
    assert tool_schemas_from({"tools": [{"no_name": 1}]}) is None
    assert tool_schemas_from("not a mapping") is None


def test_llm_boundary_records_the_tools_it_was_given():
    @boundary("agent", kind="llm")
    def agent(messages, tools):
        return {"completion": "hi", "model": "m"}

    with chronicle.record("t") as session:
        agent([{"role": "user", "content": "x"}], tools=[OPENAI])
    (env,) = session.envelopes
    assert env.tool_schemas == [
        ToolSchema(
            name="search_docs",
            description="Search docs",
            parameters=OPENAI["function"]["parameters"],
        )
    ]


def test_llm_boundary_reads_tools_from_a_state_mapping():
    @boundary("agent", kind="llm")
    def agent(state):
        return {"completion": "hi"}

    with chronicle.record("t") as session:
        agent({"messages": [{"role": "user", "content": "x"}], "tools": [ANTHROPIC]})
    assert [s.name for s in session.envelopes[0].tool_schemas] == ["get_weather"]


def test_extract_metadata_hook_wins_over_arguments():
    @boundary("agent", kind="llm", extract_metadata=lambda r: {"tools": [PLAIN]})
    def agent(messages, tools):
        return {"completion": "hi"}

    with chronicle.record("t") as session:
        agent([], tools=[OPENAI])
    assert [s.name for s in session.envelopes[0].tool_schemas] == ["add"]


def test_llm_boundary_without_tools_records_none():
    @boundary("agent", kind="llm")
    def agent(messages):
        return {"completion": "hi"}

    with chronicle.record("t") as session:
        agent([])
    env = session.envelopes[0]
    assert env.tool_schemas == []
    assert GEN_AI_TOOL_DEFINITIONS not in env.attributes
