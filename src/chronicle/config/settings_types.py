"""``ChronicleSettings``: every setting a developer can set that Chronicle honours (design 9).

Precedence: code (``chronicle.configure(...)``), then environment (``CHRONICLE_*``), then the
config file. Environment names are the setting name upper-cased with dots as underscores, for
example ``CHRONICLE_HOOKS_FAIL_CALL_ON_ERROR``.

``enabled`` and hooks: ``enabled = False`` switches recording off (no envelopes, no trace
registration, no writes) and **does not disable hooks**. Turning recording off must not turn
governance off. This resolves the open question in issue #60.
"""

from dataclasses import dataclass, field

from chronicle.config.config_enums import OverflowPolicy, TraceRegistration
from chronicle.framework.redaction.redactor_types import Redactor


@dataclass(frozen=True)
class ChronicleSettings:
    """The configuration surface. Defaults are the documented defaults."""

    # Core
    enabled: bool = True
    """Master switch for recording. Does not disable hooks."""
    control_plane_url: str | None = None
    """Where to save. With no URL nothing is delivered (hooks and replay still work)."""
    api_key: str | None = None
    service_name: str = "agent"
    """Names the service on its spans."""

    # Capture
    capture_input: bool = True
    capture_output: bool = True
    max_payload_bytes: int | None = None
    """Cap on one string value in a payload; longer strings are truncated."""

    # Redaction
    redactors: tuple[Redactor, ...] = field(default_factory=tuple)
    default_redactors: bool = False
    """Opt in to ``default_redactors()`` (masks common secret shapes) before your own."""

    # Propagation
    extract: bool = True
    """Join a valid inbound ``traceparent``."""
    inject: bool = True
    inject_hosts: tuple[str, ...] = ()
    """Allow-list of hosts that receive ``traceparent``. Default deny: empty means none."""

    # Hooks
    hooks_fail_call_on_error: bool = False
    """Whether a hook failure fails the call. ``AbortCall`` always propagates."""

    # Delivery
    batch_size: int = 50
    flush_interval: float = 1.0
    max_queue: int = 10_000
    on_overflow: OverflowPolicy = OverflowPolicy.DROP
    timeout: float = 5.0
    fail_open: bool = True
    """Fail-open carries on without the control plane; strict (False) fails the operation."""

    # Trace registration
    trace_registration: TraceRegistration = TraceRegistration.SYNC
    registration_fail_open: bool = True

    # Intent capture
    emit_open: bool = False
    """Send an open write for each envelope (see design 2.4 and 6.3)."""
