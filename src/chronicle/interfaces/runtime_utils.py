"""Process-wide wiring: settings, control-plane client, delivery queue and the ambient span.

This is where the configuration (design section 9) meets the layers below it. Precedence is
code (``configure``), then ``CHRONICLE_*`` environment, then the config file. The delivery queue
and the HTTP client are built lazily from the settings and rebuilt when the settings that shape
them change.

**Ambient span.** A boundary called outside any span (a plain script, a notebook) is recorded
into one process-wide span that is minted on first use and closed at exit. A web service should
use the ASGI middleware or ``chronicle.span()`` so each request gets its own span.
"""

import atexit
import logging
import threading
from collections.abc import Mapping
from typing import Any

from chronicle.capabilities.record.record_environment_types import RecordEnvironment
from chronicle.capabilities.record.recorder import close_span, start_request
from chronicle.config.settings_types import ChronicleSettings
from chronicle.config.settings_utils import effective_redactors, load_settings
from chronicle.framework.context.recording_session import RecordingSession
from chronicle.framework.context.session_context_utils import current_session
from chronicle.framework.context.session_settings_types import SessionSettings
from chronicle.framework.hooks.hook_registry import default_hooks
from chronicle.framework.interceptor.interceptor import Interceptor
from chronicle.repositories.delivery_types import DeliveryPolicy
from chronicle.repositories.http_control_plane_client import HttpControlPlaneClient
from chronicle.repositories.queued_envelope_sink import QueuedEnvelopeSink
from chronicle.repositories.repository_types import ControlPlaneClient

_log = logging.getLogger("chronicle")


class _State:
    """Mutable process-wide state, guarded by ``lock``."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.overrides: dict[str, Any] = {}
        self.client_override: ControlPlaneClient | None = None
        self.client: ControlPlaneClient | None = None
        self.sink: QueuedEnvelopeSink | None = None
        self.sink_key: object = None
        self.ambient: RecordingSession | None = None
        self.ambient_key: object = None


_state = _State()


def configure(*, client: ControlPlaneClient | None = None, **settings: Any) -> None:
    """Set configuration in code (the highest precedence) and/or inject a control-plane client.

    ``chronicle.configure(control_plane_url="http://cp:8000", api_key="...", inject_hosts=["b"])``
    Unknown setting names raise ``ValueError``. Settings are merged with earlier calls.
    """
    with _state.lock:
        candidate = {**_state.overrides, **settings}
        load_settings(candidate)  # validate names and values before keeping them
        _state.overrides = candidate
        if client is not None:
            _state.client_override = client
        _close_ambient()


def reset() -> None:
    """Forget code configuration and injected client, flush, and stop background delivery."""
    with _state.lock:
        _close_ambient()
        sink, _state.sink = _state.sink, None
        _state.sink_key = None
        _state.client = None
        _state.client_override = None
        _state.overrides = {}
    if sink is not None:
        sink.close()


def get_settings() -> ChronicleSettings:
    """The current settings: code, then environment, then config file."""
    return load_settings(_state.overrides)


def is_enabled() -> bool:
    """Whether recording is on. Hooks run regardless (design section 9)."""
    return get_settings().enabled


def session_settings(settings: ChronicleSettings | None = None) -> SessionSettings:
    """The subset of the settings a recording session honours."""
    current = settings or get_settings()
    return SessionSettings(
        recording=current.enabled,
        capture_input=current.capture_input,
        capture_output=current.capture_output,
        max_payload_bytes=current.max_payload_bytes,
        redactors=effective_redactors(current),
        emit_open=current.emit_open,
        fail_call_on_error=current.hooks_fail_call_on_error,
    )


def get_environment(settings: ChronicleSettings | None = None) -> RecordEnvironment:
    """Build the record environment, creating the client and delivery queue on first use."""
    current = settings or get_settings()
    client, sink = _client_and_sink(current)
    return RecordEnvironment(
        service=current.service_name,
        settings=session_settings(current),
        hooks=default_hooks,
        sink=sink,
        client=client,
        trace_registration=current.trace_registration,
        registration_fail_open=current.registration_fail_open,
    )


def get_client() -> ControlPlaneClient | None:
    """The control-plane client in use, if any (used by replay)."""
    return get_environment().client


def flush() -> None:
    """Deliver everything queued so far (raises in strict mode if a delivery failed)."""
    sink = _state.sink
    if sink is not None:
        sink.flush()


def shutdown() -> None:
    """Close the ambient span and flush. Safe to call more than once."""
    with _state.lock:
        _close_ambient()
    flush()


def session_provider() -> RecordingSession:
    """The session a boundary crossing uses: the active span, else the ambient one."""
    active = current_session()
    if active is not None:
        return active
    return _ambient_session()


def _client_and_sink(
    settings: ChronicleSettings,
) -> tuple[ControlPlaneClient | None, QueuedEnvelopeSink | None]:
    with _state.lock:
        if _state.client_override is not None:
            client: ControlPlaneClient | None = _state.client_override
            key: object = ("override", id(client), _policy(settings))
        elif settings.control_plane_url:
            client = None
            key = (
                "http",
                settings.control_plane_url,
                settings.api_key,
                settings.timeout,
                _policy(settings),
            )
        else:
            return None, None
        if _state.sink is not None and _state.sink_key == key:
            return _state.client, _state.sink
        if _state.sink is not None:
            # Stop the old delivery thread; an injected client belongs to the caller.
            _state.sink.close(close_client=_state.client_override is None)
            _state.sink = None
        if client is None:
            assert settings.control_plane_url is not None
            client = HttpControlPlaneClient(
                settings.control_plane_url, api_key=settings.api_key, timeout=settings.timeout
            )
        _state.client = client
        _state.sink = QueuedEnvelopeSink(client, _policy(settings))
        _state.sink_key = key
        return _state.client, _state.sink


def _policy(settings: ChronicleSettings) -> DeliveryPolicy:
    return DeliveryPolicy(
        batch_size=settings.batch_size,
        flush_interval=settings.flush_interval,
        max_queue=settings.max_queue,
        on_overflow=settings.on_overflow,
        timeout=settings.timeout,
        fail_open=settings.fail_open,
    )


def _ambient_session() -> RecordingSession:
    settings = get_settings()
    key = (settings.enabled, settings.service_name)
    with _state.lock:
        if _state.ambient is not None and _state.ambient_key == key:
            return _state.ambient
        _close_ambient()
        env = get_environment(settings)
        if not settings.enabled:
            # Recording is off: a session that carries hooks only. It shares the live default
            # registry so a hook registered later still applies.
            session = RecordingSession(
                trace_id="0" * 31 + "1",
                span_id="0" * 15 + "1",
                service=settings.service_name,
                settings=env.settings,
                hooks=default_hooks,
            )
        else:
            session = start_request(env, context=None)
            session.hooks = default_hooks
        _state.ambient = session
        _state.ambient_key = key
        return session


def _close_ambient() -> None:
    session, _state.ambient = _state.ambient, None
    _state.ambient_key = None
    if session is None or not session.settings.recording:
        return
    try:
        close_span(get_environment(), session, failed=False)
    except Exception:
        _log.warning("chronicle could not close the ambient span", exc_info=True)


def overrides_snapshot() -> Mapping[str, Any]:
    """The settings passed to ``configure`` (for tests and diagnostics)."""
    return dict(_state.overrides)


interceptor = Interceptor(session_provider)
"""The process-wide interceptor every public entry point goes through."""

atexit.register(shutdown)
