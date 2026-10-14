"""``extract``, ``inject`` and the injection allow-list (design sections 3.2, 8.2 and 8.3).

Propagation uses the W3C ``traceparent`` header: ``00-<trace_id>-<parent-id>-<flags>``. The
``parent-id`` field carries the **caller's outbound-call envelope id**; the parent span id is not
passed, because the control plane resolves envelope to span.

**Allow-list (security default).** LLM SDKs use ``httpx`` internally. Without a filter the header
would be sent to third parties such as ``api.openai.com``, leaking trace ids and double-recording
the call. Injection by the instrumenters happens **only to configured hosts** (``inject_hosts``);
the default is deny. The custom ``inject`` below is an explicit call by the developer; pass
``url=`` to apply the allow-list to it as well.

Parsing is done by primitives (``parse_traceparent`` never raises: anything it does not accept
gives ``None`` and the service mints a new trace).
"""

from collections.abc import Mapping
from urllib.parse import urlsplit

from agentplane_primitives.models import TraceContext
from agentplane_primitives.utils import format_traceparent, parse_traceparent

from chronicle.framework.context.session_context_utils import current_envelope_id, current_session
from chronicle.interfaces.runtime_utils import get_settings

TRACEPARENT = "traceparent"


def extract(headers: Mapping[str, str] | None) -> TraceContext | None:
    """Return the trace context in ``headers`` (any header-name case), or ``None``."""
    if not headers:
        return None
    for key, value in headers.items():
        if key.lower() == TRACEPARENT:
            return parse_traceparent(value)
    return None


def current_trace_context() -> TraceContext | None:
    """The context to send downstream: this trace and the innermost crossing in progress."""
    session = current_session()
    envelope_id = current_envelope_id()
    if session is None or envelope_id is None or session.is_replay:
        return None
    return TraceContext(trace_id=session.trace_id, parent_envelope_id=envelope_id)


def is_allowed_host(url: str, allowed: tuple[str, ...]) -> bool:
    """True if the host (or host:port) of ``url`` is in the allow-list. Empty list: deny all."""
    if not allowed:
        return False
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if not host:
        return False
    hostport = f"{host}:{parts.port}" if parts.port else host
    wanted = {entry.strip().lower() for entry in allowed}
    return host in wanted or hostport in wanted


def inject(headers: Mapping[str, str] | None = None, *, url: str | None = None) -> dict[str, str]:
    """Return a copy of ``headers`` with ``traceparent`` set from the current crossing.

    Call it inside a boundary-wrapped client function, so the envelope in progress is the
    outbound call. With no active crossing, or with ``inject`` switched off, the headers are
    returned unchanged. If ``url`` is given, the header is added only when its host is in
    ``inject_hosts``.
    """
    result = dict(headers or {})
    settings = get_settings()
    if not settings.inject:
        return result
    if url is not None and not is_allowed_host(url, settings.inject_hosts):
        return result
    context = current_trace_context()
    if context is not None:
        result[TRACEPARENT] = format_traceparent(context)
    return result


def coerce_parent(parent: TraceContext | Mapping[str, str] | None) -> TraceContext | None:
    """Accept a ``TraceContext`` or inbound headers and return a ``TraceContext`` or ``None``."""
    if parent is None or isinstance(parent, TraceContext):
        return parent
    if not get_settings().extract:  # headers are not trusted when extraction is off
        return None
    return extract(parent)
