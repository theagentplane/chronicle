"""Method boundaries record the input schema and return shape inferred from the wrapped
method; an LLM boundary records the tools it was given. Both land in span attributes."""

from __future__ import annotations

import json
from typing import Literal

import chronicle
from chronicle import boundary
from chronicle.envelope.genai import (
    GEN_AI_OPERATION_NAME,
    GEN_AI_TOOL_DEFINITIONS,
    GEN_AI_TOOL_DESCRIPTION,
    GEN_AI_TOOL_NAME,
    ToolSchema,
    infer_method_schema,
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


def test_infer_method_schema_from_signature_return_type_and_docstring():
    def delete_file(path: str, force: bool = False, mode: Literal["soft", "hard"] = "soft") -> dict:
        """Delete a file.

        Longer details that are not part of the description.
        """

    schema = infer_method_schema(delete_file, "delete_file")
    assert schema.name == "delete_file"
    assert schema.description == "Delete a file."
    assert schema.input["type"] == "object"
    assert schema.input["required"] == ["path"]
    assert schema.input["properties"]["path"] == {"type": "string"}
    assert schema.input["properties"]["force"]["type"] == "boolean"
    assert schema.input["properties"]["mode"]["enum"] == ["soft", "hard"]
    assert "additionalProperties" not in schema.input
    assert schema.output["type"] == "object"


def test_untyped_method_still_records_its_input_field_names():
    def lookup(order_id, retries=3):
        return {"ok": True}

    schema = infer_method_schema(lookup, "lookup")
    assert list(schema.input["properties"]) == ["order_id", "retries"]
    assert schema.input["required"] == ["order_id"]
    assert "type" not in schema.input["properties"]["order_id"]
    assert schema.output is None  # nothing declared, nothing invented


def test_infer_method_schema_never_raises():
    class Opaque:
        pass

    def weird(x: Opaque, y):  # not JSON-schematizable
        return x

    schema = infer_method_schema(weird, "weird")
    assert schema.name == "weird"
    assert list(schema.input["properties"]) == ["x", "y"]


def test_string_annotations_are_resolved_for_the_return_type():
    # This module uses ``from __future__ import annotations``: every hint is a string.
    def count(items: list[str]) -> int:
        return len(items)

    schema = infer_method_schema(count, "count")
    assert schema.input["properties"]["items"]["type"] == "array"
    assert schema.output == {"type": "integer"}


def test_every_method_boundary_records_input_and_output_schema():
    @boundary("route", kind="router")
    def route(state: dict) -> str:
        return "b"

    @boundary("plain")
    def plain(a, b=2):
        return a

    with chronicle.record("t") as session:
        route({"x": 1})
        plain(1)
    routed, untyped = session.envelopes
    assert routed.input_schema["required"] == ["state"]
    assert routed.output_schema == {"type": "string"}
    assert list(untyped.input_schema["properties"]) == ["a", "b"]
    assert untyped.output_schema is None
    # Only tool boundaries follow the GenAI execute-tool convention.
    for env in (routed, untyped):
        assert GEN_AI_TOOL_NAME not in env.attributes
        assert GEN_AI_TOOL_DEFINITIONS not in env.attributes


def test_tool_boundary_follows_the_genai_execute_tool_convention():
    @boundary("delete_file", kind="tool")
    def delete_file(path: str, force: bool = False) -> dict:
        """Delete a file from disk."""
        return {"status": "deleted", "path": path}

    with chronicle.record("t") as session:
        delete_file("/tmp/x")
    (env,) = session.envelopes
    assert env.attributes[GEN_AI_OPERATION_NAME] == "execute_tool"
    assert env.attributes[GEN_AI_TOOL_NAME] == "delete_file"
    assert env.attributes[GEN_AI_TOOL_DESCRIPTION] == "Delete a file from disk."
    (schema,) = env.tool_schemas
    assert schema.parameters["required"] == ["path"]
    assert env.input_schema == schema.parameters
    assert env.output_schema["type"] == "object"


def test_tool_definitions_conform_to_the_semconv_function_tool_schema():
    """Each item needs ``type: function`` and a ``name`` (semconv gen-ai-tool-definitions)."""

    @boundary("delete_file", kind="tool")
    def delete_file(path: str):
        """Delete."""
        return {}

    @boundary("agent", kind="llm")
    def agent(messages, tools):
        return {"completion": "hi"}

    with chronicle.record("t") as session:
        delete_file("/x")
        agent([], tools=[OPENAI])
    for env in session.envelopes:
        definitions = json.loads(env.attributes[GEN_AI_TOOL_DEFINITIONS])
        assert definitions and all(d["type"] == "function" and d["name"] for d in definitions)


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
