"""The ``httpx`` instrumenter: outbound calls are tool boundaries (design sections 6.1, 8.3).

    chronicle.instrument_httpx()   # once, at startup; idempotent

For every request to an **allow-listed host** (``inject_hosts``; default deny) the call is
recorded as a ``tool`` envelope and the envelope's id is injected as the ``traceparent``
parent-id, so the downstream span's ``parent_envelope_id`` is that envelope. Requests to any
other host (the LLM provider, say) are neither recorded nor given the header: that is what stops
trace ids leaking to third parties and the LLM call being recorded twice.

Mechanism: ``Client.send`` and ``AsyncClient.send`` are patched once. A2A and other protocols
built on ``httpx`` are covered with no protocol-specific code.

**``httpx`` and ``httpx2``.** Recent LLM SDKs (``openai`` 3, ``anthropic`` 1) moved to
``httpx2``, a separate, API-compatible package. Both are patched when installed, so a peer
called through either is covered. The LLM SDKs' own traffic is to hosts that are not on the
allow-list in any case.

The recorded input is ``{method, url, headers, body}`` and the output is ``{status_code,
headers, body}``. Credentials in headers (``authorization``, ``cookie``, ``x-api-key``, ...)
are never stored. A response that is streamed is recorded with ``body = null``. In a REPLAY
STUB the recorded response is rebuilt as a response object.
"""

import importlib
import importlib.util
import json
from collections.abc import Mapping
from types import ModuleType
from typing import Any

from agentplane_primitives.enums import Kind
from agentplane_primitives.models import TraceContext
from agentplane_primitives.utils import format_traceparent
from pydantic import JsonValue

from chronicle.framework.boundary_spec_types import BoundarySpec
from chronicle.framework.context.session_context_utils import current_envelope_id, current_session
from chronicle.framework.redaction.redactor_types import REDACTED
from chronicle.interfaces.boundary_api import make_spec
from chronicle.interfaces.propagation_api import TRACEPARENT, is_allowed_host
from chronicle.interfaces.runtime_utils import get_settings, interceptor
from chronicle.repositories.http_control_plane_client import INTERNAL_EXTENSION

SUPPORTED_MODULES = ("httpx", "httpx2")

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

# module name -> (original Client.send, original AsyncClient.send)
_patched: dict[str, tuple[Any, Any]] = {}


def instrument_httpx() -> None:
    """Patch ``httpx`` (and ``httpx2`` if installed) once; idempotent."""
    for name in SUPPORTED_MODULES:
        if name in _patched or importlib.util.find_spec(name) is None:
            continue
        _patch(importlib.import_module(name))


def uninstrument_httpx() -> None:
    """Restore the original methods."""
    for name, (original_send, original_asend) in list(_patched.items()):
        module = importlib.import_module(name)
        module.Client.send = original_send
        module.AsyncClient.send = original_asend
        del _patched[name]


def _patch(module: ModuleType) -> None:
    original_send = module.Client.send
    original_asend = module.AsyncClient.send

    def send(self: Any, request: Any, **kwargs: Any) -> Any:
        if not _applies(request):
            return original_send(self, request, **kwargs)
        spec = _spec(request)

        def perform(req: Any) -> Any:
            _inject_header(req)
            return original_send(self, req, **kwargs)

        result = interceptor.call(spec, perform, (request,), {})
        return _as_response(module, result, request)

    async def asend(self: Any, request: Any, **kwargs: Any) -> Any:
        if not _applies(request):
            return await original_asend(self, request, **kwargs)
        spec = _spec(request)

        async def perform(req: Any) -> Any:
            _inject_header(req)
            return await original_asend(self, req, **kwargs)

        result = await interceptor.acall(spec, perform, (request,), {})
        return _as_response(module, result, request)

    module.Client.send = send
    module.AsyncClient.send = asend
    _patched[module.__name__] = (original_send, original_asend)


def _applies(request: Any) -> bool:
    if request.extensions.get(INTERNAL_EXTENSION):
        return False  # Chronicle's own traffic
    return is_allowed_host(str(request.url), get_settings().inject_hosts)


def _inject_header(request: Any) -> None:
    session = current_session()
    envelope_id = current_envelope_id()
    if session is None or envelope_id is None or session.is_replay or not get_settings().inject:
        return
    context = TraceContext(trace_id=session.trace_id, parent_envelope_id=envelope_id)
    request.headers[TRACEPARENT] = format_traceparent(context)


def _spec(request: Any) -> BoundarySpec:
    url = request.url
    name = f"http {request.method} {url.host}{url.path}"
    return make_spec(
        _describe_request,
        name,
        Kind.TOOL,
        extract_input=_request_input,
        extract_result=_response_output,
    )


def _describe_request(request: Any) -> None:  # signature only; never called
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


def _request_input(request: Any) -> dict[str, JsonValue]:
    try:
        content = request.content
    except Exception:  # a streaming request body that has not been read
        content = b""
    return {
        "method": request.method,
        "url": str(request.url),
        "headers": _clean_headers(request.headers),
        "body": _body_value(content),
    }


def _response_output(response: Any) -> JsonValue:
    if not hasattr(response, "status_code"):
        return None
    try:
        body = _body_value(response.content)
    except Exception:  # a streamed response that has not been read
        body = None
    return {
        "status_code": response.status_code,
        "headers": _clean_headers(response.headers),
        "body": body,
    }


def _as_response(module: ModuleType, result: Any, request: Any) -> Any:
    """The real response passes through; a stub (recorded dict) is rebuilt as a response."""
    if isinstance(result, module.Response):
        return result
    data = result if isinstance(result, dict) else {}
    body = data.get("body")
    headers = {
        key: str(value)
        for key, value in (data.get("headers") or {}).items()
        if key.lower() not in _DROPPED_ON_REBUILD
    }
    if body is None:
        content = b""
    elif isinstance(body, str):
        content = body.encode("utf-8")
    else:
        content = json.dumps(body).encode("utf-8")
    return module.Response(
        int(data.get("status_code") or 200), headers=headers, content=content, request=request
    )
