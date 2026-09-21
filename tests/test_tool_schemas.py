"""Method boundaries record the input schema and return shape inferred from the wrapped
method, as span attributes."""

from __future__ import annotations

from typing import Literal

import chronicle
from chronicle import boundary
from chronicle.envelope.genai import infer_method_schema


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


def test_failed_method_boundary_still_records_its_schema():
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
    assert env.input_schema["required"] == ["x"]
    assert env.attributes["error.type"] == "RuntimeError"
