"""@boundary / wrap fill Metadata.tool_schemas from the tools the model was given."""

from __future__ import annotations

import chronicle
from chronicle import boundary
from chronicle.envelope.schema import ToolSchema
from chronicle.session import tool_schemas_from

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


def test_llm_boundary_records_tools_argument():
    @boundary("agent", kind="llm")
    def agent(messages, tools):
        return {"completion": "hi", "model": "m"}

    with chronicle.record("t") as session:
        agent([{"role": "user", "content": "x"}], tools=[OPENAI])
    (env,) = session.envelopes
    assert env.metadata.tool_schemas == [ToolSchema(**{
        "name": "search_docs",
        "description": "Search docs",
        "parameters": OPENAI["function"]["parameters"],
    })]


def test_llm_boundary_reads_tools_from_a_state_mapping():
    @boundary("agent", kind="llm")
    def agent(state):
        return {"completion": "hi"}

    with chronicle.record("t") as session:
        agent({"messages": [{"role": "user", "content": "x"}], "tools": [ANTHROPIC]})
    assert [s.name for s in session.envelopes[0].metadata.tool_schemas] == ["get_weather"]


def test_extract_metadata_hook_wins_over_arguments():
    @boundary("agent", kind="llm", extract_metadata=lambda r: {"tools": [PLAIN]})
    def agent(messages, tools):
        return {"completion": "hi"}

    with chronicle.record("t") as session:
        agent([], tools=[OPENAI])
    assert [s.name for s in session.envelopes[0].metadata.tool_schemas] == ["add"]


def test_tool_boundary_does_not_record_tool_schemas():
    @boundary("run", kind="tool")
    def run(tools):
        return {"status": "ok"}

    with chronicle.record("t") as session:
        run(tools=[OPENAI])
    assert session.envelopes[0].metadata.tool_schemas == []


def test_llm_boundary_without_tools_records_none():
    @boundary("agent", kind="llm")
    def agent(messages):
        return {"completion": "hi"}

    with chronicle.record("t") as session:
        agent([])
    assert session.envelopes[0].metadata.tool_schemas == []
