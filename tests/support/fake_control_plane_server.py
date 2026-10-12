"""A fake control plane over HTTP: the four things Chronicle needs, validated strictly.

It implements upsert trace, upsert span, append envelopes and read a span's envelopes, and
rejects malformed payloads by validating every body with the primitives models, exactly as the
real control plane does (both import the same package). It keeps the raw request bodies so tests
can assert on what really crossed the wire (for example that a secret never did). An optional CI
job can run the real control-plane service instead.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from agentplane_primitives.models import Envelope, Span, Trace
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


@dataclass
class FakeControlPlane:
    """State and behaviour of the fake; ``app`` is the ASGI application to serve."""

    api_key: str | None = None
    down: bool = False
    """When true every request fails with 503 (the control plane is unreachable)."""
    traces: dict[str, Trace] = field(default_factory=dict)
    spans: dict[tuple[str, str], Span] = field(default_factory=dict)
    envelopes: dict[tuple[str, str], Envelope] = field(default_factory=dict)
    raw_bodies: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)

    @property
    def app(self) -> Starlette:
        return Starlette(
            routes=[
                Route("/v1/traces", self._post_trace, methods=["POST"]),
                Route("/v1/traces/{trace_id}/spans/{span_id}", self._put_span, methods=["PUT"]),
                Route("/v1/envelopes:batch", self._post_envelopes, methods=["POST"]),
                Route(
                    "/v1/traces/{trace_id}/spans/{span_id}/envelopes",
                    self._get_span_envelopes,
                    methods=["GET"],
                ),
            ]
        )

    # ---- helpers -----------------------------------------------------------------------

    def _gate(self, request: Request) -> JSONResponse | None:
        if self.down:
            return JSONResponse({"detail": "control plane is down"}, status_code=503)
        wanted = f"Bearer {self.api_key}"
        if self.api_key is not None and request.headers.get("authorization") != wanted:
            return JSONResponse({"detail": "invalid api key"}, status_code=401)
        return None

    async def _body(self, request: Request) -> tuple[Any, str]:
        raw = (await request.body()).decode("utf-8")
        self.raw_bodies.append(raw)
        return json.loads(raw), raw

    def _reject(self, detail: str) -> JSONResponse:
        self.rejected.append(detail)
        return JSONResponse({"detail": detail}, status_code=400)

    # ---- endpoints ---------------------------------------------------------------------

    async def _post_trace(self, request: Request) -> JSONResponse:
        if (blocked := self._gate(request)) is not None:
            return blocked
        payload, _ = await self._body(request)
        try:
            trace = Trace.model_validate(payload)
        except ValidationError as exc:
            return self._reject(str(exc))
        created = trace.trace_id not in self.traces
        self.traces.setdefault(trace.trace_id, trace)  # idempotent; labels written once
        return JSONResponse({"trace_id": trace.trace_id}, status_code=201 if created else 200)

    async def _put_span(self, request: Request) -> JSONResponse:
        if (blocked := self._gate(request)) is not None:
            return blocked
        payload, _ = await self._body(request)
        try:
            span = Span.model_validate(payload)
        except ValidationError as exc:
            return self._reject(str(exc))
        if (span.trace_id, span.span_id) != (
            request.path_params["trace_id"],
            request.path_params["span_id"],
        ):
            return self._reject("path ids do not match the body")
        self.spans[(span.trace_id, span.span_id)] = span
        return JSONResponse({"span_id": span.span_id}, status_code=200)

    async def _post_envelopes(self, request: Request) -> JSONResponse:
        if (blocked := self._gate(request)) is not None:
            return blocked
        payload, _ = await self._body(request)
        items = payload.get("envelopes") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return self._reject("expected {envelopes: [...]}")
        parsed: list[Envelope] = []
        for item in items:
            try:
                parsed.append(Envelope.model_validate(item))
            except ValidationError as exc:
                return self._reject(str(exc))
        deduped = 0
        for envelope in parsed:
            key = (envelope.trace_id, envelope.envelope_id)
            deduped += key in self.envelopes
            self.envelopes[key] = envelope  # an open record is updated when its close arrives
        return JSONResponse(
            {"status": "stored", "accepted": len(parsed), "deduped": deduped}, status_code=201
        )

    async def _get_span_envelopes(self, request: Request) -> JSONResponse:
        if (blocked := self._gate(request)) is not None:
            return blocked
        trace_id = request.path_params["trace_id"]
        span_id = request.path_params["span_id"]
        found = [
            e.model_dump(mode="json")
            for (t, _), e in self.envelopes.items()
            if t == trace_id and e.span_id == span_id
        ]
        return JSONResponse({"envelopes": found})

    # ---- assertions helpers ------------------------------------------------------------

    def span_for(self, trace_id: str, service: str) -> Span:
        """The one span of ``service`` in ``trace_id`` (fails if there is not exactly one)."""
        found = [s for s in self.spans.values() if s.trace_id == trace_id and s.service == service]
        assert len(found) == 1, f"expected one span for {service}, found {len(found)}"
        return found[0]

    def envelopes_of(self, span: Span) -> list[Envelope]:
        mine = [e for e in self.envelopes.values() if e.span_id == span.span_id]

        def order(envelope: Envelope) -> int:
            value = envelope.metadata.get("chronicle.sequence", 0)
            return value if isinstance(value, int) else 0

        return sorted(mine, key=order)
