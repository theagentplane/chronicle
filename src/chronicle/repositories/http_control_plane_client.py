"""``HttpControlPlaneClient``: the control plane over HTTP (design sections 5.1 and 5.2).

Request bodies are the primitives entities in their JSON form. Responses are read with the
tolerant wire models (``wire_types``). Requests carry the extension ``chronicle.internal`` so the
``httpx`` instrumenter never records or injects into Chronicle's own traffic.
"""

import json
from collections.abc import Sequence
from typing import Any

import httpx
from agentplane_primitives.models import Envelope, Span, Trace
from pydantic import ValidationError

from chronicle.repositories import http_endpoints
from chronicle.repositories.errors import ControlPlaneError
from chronicle.repositories.wire_types import ErrorBody

INTERNAL_EXTENSION = "chronicle.internal"
"""Request extension that marks Chronicle's own calls; instrumenters skip them."""


class HttpControlPlaneClient:
    """Talks to the control plane. Safe to share between threads."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout: float = 5.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        headers = {"Content-Type": "application/json", "User-Agent": "agent-chronicle"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
            transport=transport,
        )

    # ---- writes ------------------------------------------------------------------------

    def upsert_trace(self, trace: Trace) -> None:
        self._send("POST", http_endpoints.TRACES, _dump(trace))

    def upsert_span(self, span: Span) -> None:
        self._send("PUT", http_endpoints.span_path(span.trace_id, span.span_id), _dump(span))

    def append_envelopes(self, envelopes: Sequence[Envelope]) -> None:
        if not envelopes:
            return
        body = {"envelopes": [_dump(envelope) for envelope in envelopes]}
        self._send("POST", http_endpoints.ENVELOPES_BATCH, body)

    # ---- read (replay only) ------------------------------------------------------------

    def read_span_envelopes(self, trace_id: str, span_id: str) -> list[Envelope]:
        response = self._send("GET", http_endpoints.span_envelopes_path(trace_id, span_id), None)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ControlPlaneError("control plane returned a body that is not JSON") from exc
        items = payload.get("envelopes") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise ControlPlaneError("control plane response has no 'envelopes' list")
        try:
            return [Envelope.model_validate(item) for item in items]
        except ValidationError as exc:
            raise ControlPlaneError(f"control plane returned an invalid envelope: {exc}") from exc

    def close(self) -> None:
        self._client.close()

    # ---- internals ---------------------------------------------------------------------

    def _send(self, method: str, path: str, body: Any) -> httpx.Response:
        try:
            response = self._client.request(
                method,
                path,
                content=None if body is None else json.dumps(body).encode("utf-8"),
                extensions={INTERNAL_EXTENSION: True},
            )
        except httpx.HTTPError as exc:
            raise ControlPlaneError(f"control plane unreachable: {exc}") from exc
        if response.status_code >= 400:
            raise ControlPlaneError(
                f"control plane returned {response.status_code}: {_error_detail(response)}",
                status_code=response.status_code,
            )
        return response


def _dump(model: Trace | Span | Envelope) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude_none=True)


def _error_detail(response: httpx.Response) -> str:
    try:
        body = ErrorBody.model_validate(response.json())
    except (ValueError, ValidationError):
        return response.text[:200]
    for candidate in (body.detail, body.message, body.error):
        if candidate:
            return str(candidate)[:200]
    return response.text[:200]
