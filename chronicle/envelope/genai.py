"""Typed, checked views of what a boundary was configured with, flattened into OTel
attributes.

An Envelope does not carry a separate metadata object: the model and sampling
parameters live in ``Envelope.attributes`` under the OpenTelemetry
GenAI semantic-convention keys. The conventions live in the
``open-telemetry/semantic-conventions-genai`` repository and are Development status, so
key names can still change; ``tests/test_genai_attributes.py`` pins ours to the released
``opentelemetry-semantic-conventions`` package. The classes here exist so a boundary can
capture those values as *validated fields*, and ``to_attributes()`` turns them into the
flat attributes the envelope stores.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Mapping
from typing import Any, Callable, Union, get_type_hints

from pydantic import BaseModel, Field, TypeAdapter

# OTel attribute values: primitives or homogeneous lists of primitives.
AttributeValue = Union[str, bool, int, float, list[str], list[bool], list[int], list[float]]

# GenAI semantic-convention keys.
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_PROVIDER_NAME = "gen_ai.provider.name"
GEN_AI_REQUEST_TEMPERATURE = "gen_ai.request.temperature"
GEN_AI_REQUEST_TOP_P = "gen_ai.request.top_p"
GEN_AI_REQUEST_MAX_TOKENS = "gen_ai.request.max_tokens"
GEN_AI_REQUEST_SEED = "gen_ai.request.seed"

# Chronicle's own keys: the JSON schema of a boundary method's input and output.
CHRONICLE_INPUT_SCHEMA = "chronicle.input.schema"
CHRONICLE_OUTPUT_SCHEMA = "chronicle.output.schema"


class LLMRequest(BaseModel):
    """What an LLM call was configured with. Validated at capture time, then stored
    only as attributes (see :meth:`to_attributes`)."""

    model: str | None = None
    provider: str | None = None
    sampling: SamplingParams = Field(default_factory=lambda: SamplingParams())

    def to_attributes(self) -> dict[str, AttributeValue]:
        attributes: dict[str, AttributeValue] = {}
        if self.model:
            attributes[GEN_AI_REQUEST_MODEL] = self.model
        if self.provider:
            attributes[GEN_AI_PROVIDER_NAME] = self.provider
        if self.sampling.temperature is not None:
            attributes[GEN_AI_REQUEST_TEMPERATURE] = self.sampling.temperature
        if self.sampling.top_p is not None:
            attributes[GEN_AI_REQUEST_TOP_P] = self.sampling.top_p
        if self.sampling.max_tokens is not None:
            attributes[GEN_AI_REQUEST_MAX_TOKENS] = self.sampling.max_tokens
        if self.sampling.seed is not None:
            attributes[GEN_AI_REQUEST_SEED] = self.sampling.seed
        return attributes


class MethodSchema(BaseModel):
    """The shape of a boundary method: its input parameters and its return type.

    ``input`` is a JSON schema of the signature. It always names every parameter, and adds
    types, defaults and ``required`` where the method is annotated, so an unannotated
    method still records its field names. ``output`` is the JSON schema of the return
    annotation, or ``None`` when the method declares none.
    """

    name: str
    description: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None

    def to_attributes(self) -> dict[str, AttributeValue]:
        """Span attributes for this method: ``chronicle.input.schema`` and, when the return
        is annotated, ``chronicle.output.schema``."""
        attributes: dict[str, AttributeValue] = {
            CHRONICLE_INPUT_SCHEMA: json.dumps(self.input, sort_keys=True),
        }
        if self.output is not None:
            attributes[CHRONICLE_OUTPUT_SCHEMA] = json.dumps(self.output, sort_keys=True)
        return attributes


class SamplingParams(BaseModel):
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    seed: int | None = None


# --------------------------------------------------------------------------- #
# Capture helpers: best-effort extraction from call arguments / results.
# --------------------------------------------------------------------------- #


def infer_method_schema(fn: Callable[..., Any], name: str) -> MethodSchema:
    """Infer a boundary method's schema from the method itself.

    The input is the JSON schema of the signature and the output is the JSON schema of the
    return annotation. The description is the docstring's first paragraph. When the method
    is not annotated the input still records the untyped parameter names, and the output
    is left out. Never raises: an unschematizable signature keeps just its parameter names.
    """
    doc = inspect.getdoc(fn) or ""
    description = doc.split("\n\n")[0].replace("\n", " ").strip() or None
    try:
        input_schema = TypeAdapter(fn).json_schema()
    except Exception:
        input_schema = {"type": "object", "properties": _parameter_names(fn)}
    input_schema.pop("additionalProperties", None)
    for prop in input_schema.get("properties", {}).values():
        if isinstance(prop, dict):
            prop.pop("title", None)
    return MethodSchema(
        name=name, description=description, input=input_schema, output=_return_schema(fn)
    )


def _parameter_names(fn: Callable[..., Any]) -> dict[str, dict[str, Any]]:
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return {}
    return {
        p: {}
        for p, param in params.items()
        if p not in ("self", "cls")
        and param.kind not in (param.VAR_POSITIONAL, param.VAR_KEYWORD)
    }


def _return_schema(fn: Callable[..., Any]) -> dict[str, Any] | None:
    try:
        annotation = inspect.signature(fn).return_annotation
        if annotation is inspect.Signature.empty:
            return None
        if isinstance(annotation, str):  # ``from __future__ import annotations``
            annotation = get_type_hints(fn).get("return", inspect.Signature.empty)
            if annotation is inspect.Signature.empty:
                return None
        schema = TypeAdapter(annotation).json_schema()
    except Exception:
        return None
    schema.pop("title", None)
    return schema


def sampling_params_from(source: Any) -> SamplingParams | None:
    """Best-effort extraction of sampling parameters from a result or request kwargs.

    Recognizes either a nested ``sampling_params`` mapping or the flat keys
    (temperature, top_p, max_tokens, seed) that common LLM SDKs use. Returns ``None``
    when nothing recognizable is present.
    """
    if not isinstance(source, Mapping):
        return None
    nested = source.get("sampling_params")
    if isinstance(nested, Mapping):
        source = nested
    keys = ("temperature", "top_p", "max_tokens", "seed")
    if not any(k in source for k in keys):
        return None
    return SamplingParams(
        temperature=source.get("temperature"),
        top_p=source.get("top_p"),
        max_tokens=source.get("max_tokens"),
        seed=source.get("seed"),
    )


def model_from(source: Any) -> str | None:
    """Best-effort extraction of the resolved model from a result or request kwargs.

    Prefers an explicit ``model_version`` and falls back to ``model`` (what most SDK
    responses echo back). Returns ``None`` when neither is present.
    """
    if not isinstance(source, Mapping):
        return None
    value = source.get("model_version") or source.get("model")
    return str(value) if value else None
