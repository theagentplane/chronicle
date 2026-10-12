"""ASGI middleware: join a valid inbound ``traceparent``, else mint (design sections 6.1, 8.2).

    app = ChronicleMiddleware(app, service="orchestrator")          # any ASGI app
    app.add_middleware(ChronicleMiddleware, service="orchestrator")  # Starlette / FastAPI

For each HTTP or WebSocket request one span is opened. A valid ``traceparent`` joins that trace
and the span's ``parent_envelope_id`` is the received id; a missing or malformed header mints a
new trace (and registers it) and never raises. The span closes when the handler returns
(``success``) or raises (``failure``, and the exception propagates), and the queue is flushed.

Trust: a well-formed header proves neither that the trace exists nor that the sender is
legitimate. On internet-facing services switch ``extract`` off (design section 12.1).
"""

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from agentplane_primitives.models import TraceContext
from agentplane_primitives.utils import parse_traceparent

from chronicle.capabilities.record.recorder import arecord_request
from chronicle.interfaces.runtime_utils import get_environment, get_settings

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class ChronicleMiddleware:
    """Pure ASGI middleware (not ``BaseHTTPMiddleware``, so it does not buffer or re-task)."""

    def __init__(self, app: ASGIApp, *, service: str | None = None) -> None:
        self.app = app
        self.service = service

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        settings = get_settings()
        context: TraceContext | None = None
        if settings.extract:
            context = parse_traceparent(_header(scope, b"traceparent"))
        async with arecord_request(
            get_environment(settings), context=context, service=self.service
        ):
            await self.app(scope, receive, send)


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers") or ():
        if key.lower() == name:
            try:
                return bytes(value).decode("latin-1")
            except (TypeError, UnicodeDecodeError):
                return None
    return None
