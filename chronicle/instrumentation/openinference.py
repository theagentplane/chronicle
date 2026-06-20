"""OpenInference and Phoenix bootstrap for framework-agnostic tracing."""

from __future__ import annotations

import os
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter


def bootstrap_tracing(
    *,
    service_name: str = "chronicle",
    phoenix_endpoint: str | None = None,
    console: bool = False,
) -> trace.Tracer:
    """
    Initialize OpenTelemetry tracing with optional Phoenix OTLP export.

    When phoenix is installed, envelopes can be correlated with Phoenix traces
    via shared trace_id. OpenInference instrumentation layers on top for
    framework-agnostic span attributes.
    """
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(provider)

    endpoint = phoenix_endpoint or os.environ.get(
        "PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:4317"
    )

    if phoenix_endpoint is not False:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
            )
        except ImportError:
            pass

    if console:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    return trace.get_tracer("chronicle")


def instrument_langchain() -> None:
    """Enable OpenInference LangChain/LangGraph instrumentation."""
    try:
        from openinference.instrumentation.langchain import LangChainInstrumentor

        LangChainInstrumentor().instrument()
    except ImportError as e:
        raise ImportError(
            "Install chronicle with langgraph extras: pip install chronicle[langgraph]"
        ) from e


def span_envelope_attributes(envelope_data: dict[str, Any]) -> dict[str, Any]:
    """Map envelope fields to OpenInference-compatible span attributes."""
    return {
        "chronicle.envelope_id": envelope_data.get("envelope_id"),
        "chronicle.trace_id": envelope_data.get("trace_id"),
        "chronicle.node_id": envelope_data.get("node_id"),
        "chronicle.model_version": envelope_data.get("metadata", {}).get("model_version"),
        "chronicle.build_id": envelope_data.get("metadata", {}).get("build_id"),
        "input.value": envelope_data.get("input_state"),
        "output.value": envelope_data.get("action_result"),
    }
