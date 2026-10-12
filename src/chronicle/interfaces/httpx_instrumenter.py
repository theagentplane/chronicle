"""The ``httpx`` instrumenter: outbound calls are tool boundaries (design sections 6.1, 8.3).

    chronicle.instrument_httpx()   # once, at startup; idempotent

For every request to an **allow-listed host** (``inject_hosts``; default deny) the call is
recorded as a ``tool`` envelope and the envelope's id is injected as the ``traceparent``
parent-id, so the downstream span's ``parent_envelope_id`` is that envelope. Requests to any
other host (the LLM provider, say) are neither recorded nor given the header: that is what stops
trace ids leaking to third parties and the LLM call being recorded twice.

Mechanism: ``httpx.Client.send`` and ``httpx.AsyncClient.send`` are patched once. A2A and other
protocols built on ``httpx`` are covered with no protocol-specific code.

The recorded input is ``{method, url, headers, body}`` and the output is ``{status_code,
headers, body}``. Credentials in headers (``authorization``, ``cookie``, ``x-api-key``, ...)
are never stored. A response that is streamed is recorded with ``body = null``. In a REPLAY
STUB the recorded response is rebuilt as an ``httpx.Response``.
"""

import json
from collections.abc import Mapping
from typing import Any

import httpx
from agentplane_primitives.enums import Kind
from pydantic import JsonValue

from chronicle.framework.context.session_context_utils import current_envelope_id, current_session
from chronicle.framework.redaction.redactor_types import REDACTED
from chronicle.interfaces.boundary_api import make_spec
from chronicle.interfaces.propagation_api import TRACEPARENT, is_allowed_host
from chronicle.interfaces.runtime_utils import get_settings, interceptor
from chronicle.repositories.http_control_plane_client import INTERNAL_EXTENSION

_SENSITIVE_HEADERS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "api-key",
    "x-auth-token",
}
_DROPPED_ON_REBUILD = {"content-length", "content-encoding", "transfer-encoding"}

_original_send: Any = None
_original_asend: Any = None


def instrument_httpx() -> None:
    """Patch ``httpx`` once so allow-listed outbound calls are recorded and given the header."""
    global _original_send, _original_asend
    if _original_send is not None:
        return
    _original_send = httpx.Client.send
    _original_asend = httpx.AsyncClient.send

    def send(self: httpx.Client, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        if not _applies(request):
            return _original_send(self, request, **kwargs)  # type: ignore[no-any-return]
        spec = _spec(request)

        def perform(req: httpx.Request) -> httpx.Response:
            _inject_header(req)
            return _original_send(self, req, **kwargs)  # type: ignore[no-any-return]

        result = interceptor.call(spec, perform, (request,), {})
        return _as_response(result, request)

    async def asend(
        self: httpx.AsyncClient, request: httpx.Request, **kwargs: Any
    ) -> httpx.Response:
        if not _applies(request):
            return await _original_asend(self, request, **kwargs)  # type: ignore[no-any-return]
        spec = _spec(request)

        async def perform(req: httpx.Request) -> httpx.Response:
            _inject_header(req)
            return await _original_asend(self, req, **kwargs)  # type: ignore[no-any-return]

        result = await interceptor.acall(spec, perform, (request,), {})
        return _as_response(result, request)

    httpx.Client.send = send  # type: ignore[method-assign]
    httpx.AsyncClient.send = asend  # type: ignore[method-assign]


def uninstrument_httpx() -> None:
    """Restore the original ``httpx`` methods."""
    global _original_send, _original_asend
    if _original_send is None:
        return
    httpx.Client.send = _original_send  # type: ignore[method-assign]
    httpx.AsyncClient.send = _original_asend  # type: ignore[method-assign]
    _original_send = None
    _original_asend = None


def _applies(request: httpx.Request) -> bool:
    if request.extensions.get(INTERNAL_EXTENSION):
        return False  # Chronicle's own traffic
    settings = get_settings()
    return is_allowed_host(str(request.url), settings.inject_hosts)


def _inject_header(request: httpx.Request) -> None:
    session = current_session()
    envelope_id = current_envelope_id()
    if session is None or envelope_id is None or not get_settings().inject:
        return
    from agentplane_primitives.models import TraceContext
    from agentplane_primitives.utils import format_traceparent

    context = TraceContext(trace_id=session.trace_id, parent_envelope_id=envelope_id)
    request.headers[TRACEPARENT] = format_traceparent(context)


def _spec(request: httpx.Request) -> Any:
    url = request.url
    name = f"http {request.method} {url.host}{url.path}"
    return make_spec(
        _describe_request,
        name,
        Kind.TOOL,
        extract_input=_request_input,
        extract_result=_response_output,
    )


def _describe_request(request: httpx.Request) -> None:  # signature only; never called
    return None


def _clean_headers(headers: Mapping[str, str]) -> dict[str, JsonValue]:
    return {
        key.lower(): (REDACTED if key.lower() in _SENSITIVE_HEADERS else value)
        for key, value in headers.items()
        if key.lower() != TRACEPARENT
    }


def _body_value(content: bytes) -> JsonValue:
    if not content:
        return None
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return f"<binary {len(content)} bytes>"
    try:
        parsed: JsonValue = json.loads(text)
        return parsed
    except ValueError:
        return text


def _request_input(request: httpx.Request) -> dict[str, JsonValue]:
    try:
        content = request.content
    except httpx.RequestNotRead:
        content = b""
    return {
        "method": request.method,
        "url": str(request.url),
        "headers": _clean_headers(request.headers),
        "body": _body_value(content),
    }


def _response_output(response: Any) -> JsonValue:
    if not isinstance(response, httpx.Response):
        return None
    try:
        body = _body_value(response.content)
    except httpx.ResponseNotRead:
        body = None
    return {
        "status_code": response.status_code,
        "headers": _clean_headers(response.headers),
        "body": body,
    }


def _as_response(result: Any, request: httpx.Request) -> httpx.Response:
    """The real response passes through; a stub (recorded dict) is rebuilt as a response."""
    if isinstance(result, httpx.Response):
        return result
    data = result if isinstance(result, dict) else {}
    body = data.get("body")
    headers = {
        key: str(value)
        for key, value in (data.get("headers") or {}).items()
        if key.lower() not in _DROPPED_ON_REBUILD
    }
    content = body.encode("utf-8") if isinstance(body, str) else json.dumps(body).encode("utf-8")
    if body is None:
        content = b""
    return httpx.Response(
        int(data.get("status_code") or 200), headers=headers, content=content, request=request
    )
