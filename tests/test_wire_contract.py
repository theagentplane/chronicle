"""Contract test: the HTTP client against the control plane's write result and error body.

Primitives ADR 0003: the request and response wrappers belong to the control plane. Chronicle
imports primitives for the entities and reads the write result and the error body itself. This
test pins what Chronicle relies on, so a change to the control plane shows up here.
"""

import json

import httpx
import pytest
from agentplane_primitives.enums import State
from agentplane_primitives.models import Envelope, Trace

import chronicle
from chronicle.repositories import ControlPlaneError, HttpControlPlaneClient
from tests.support.in_memory_control_plane import InMemoryControlPlane


def _envelope() -> Envelope:
    plane = InMemoryControlPlane()
    chronicle.configure(client=plane, batch_size=1, flush_interval=0.01)

    @chronicle.boundary("t")
    def t(x: int) -> int:
        return x

    with chronicle.record("x"):
        t(1)
    chronicle.flush()
    envelope = next(iter(plane.envelopes.values()))
    chronicle.reset()
    return envelope


def _client(
    handler: httpx.MockTransport, api_key: str | None = "secret-key"
) -> HttpControlPlaneClient:
    return HttpControlPlaneClient("http://cp.test", api_key=api_key, transport=handler)


def test_envelopes_are_posted_as_a_batch_with_bearer_auth() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"status": "stored", "accepted": 1, "deduped": 0})

    envelope = _envelope()
    _client(httpx.MockTransport(handler)).append_envelopes([envelope])
    (request,) = seen
    assert request.method == "POST"
    assert request.url.path == "/v1/envelopes:batch"
    assert request.headers["authorization"] == "Bearer secret-key"
    body = json.loads(request.content)
    assert Envelope.model_validate(body["envelopes"][0]) == envelope


def test_trace_and_span_use_the_documented_paths() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(200, json={})

    client = _client(httpx.MockTransport(handler))
    client.upsert_trace(Trace(trace_id="a" * 32, state=State.OPEN))
    envelope = _envelope()
    plane = InMemoryControlPlane()
    chronicle.configure(client=plane)
    with chronicle.record("s") as session:
        pass
    chronicle.flush()
    span = plane.spans[(session.trace_id, session.span_id)]
    client.upsert_span(span)
    assert seen[0] == ("POST", "/v1/traces")
    assert seen[1] == ("PUT", f"/v1/traces/{span.trace_id}/spans/{span.span_id}")
    assert envelope.trace_id != span.trace_id


def test_read_returns_validated_envelopes() -> None:
    envelope = _envelope()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert (
            request.url.path == f"/v1/traces/{envelope.trace_id}/spans/{envelope.span_id}/envelopes"
        )
        return httpx.Response(200, json={"envelopes": [envelope.model_dump(mode="json")]})

    result = _client(httpx.MockTransport(handler)).read_span_envelopes(
        envelope.trace_id, envelope.span_id
    )
    assert result == [envelope]


def test_an_error_body_becomes_a_control_plane_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "invalid api key"})

    with pytest.raises(ControlPlaneError, match="invalid api key") as info:
        _client(httpx.MockTransport(handler)).append_envelopes([_envelope()])
    assert info.value.status_code == 401


def test_unreachable_control_plane_is_a_control_plane_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(ControlPlaneError, match="unreachable"):
        _client(httpx.MockTransport(handler)).upsert_trace(
            Trace(trace_id="a" * 32, state=State.OPEN)
        )


def test_unknown_fields_in_a_response_are_ignored() -> None:
    envelope = _envelope()
    payload = envelope.model_dump(mode="json")
    payload["added_by_a_newer_control_plane"] = {"x": 1}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"envelopes": [payload], "next": None})

    result = _client(httpx.MockTransport(handler)).read_span_envelopes(
        envelope.trace_id, envelope.span_id
    )
    assert result == [envelope]
