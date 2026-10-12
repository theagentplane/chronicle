"""``RecordEnvironment``: what the record workflow needs to open and close spans (design 6.1).

It is built by the interface layer from the configuration, so the capability itself does not
read configuration (layer rule, design section 1.1).
"""

from dataclasses import dataclass

from chronicle.capabilities.record.registration_enums import TraceRegistration
from chronicle.framework.context.envelope_sink_types import EnvelopeSink
from chronicle.framework.context.session_settings_types import SessionSettings
from chronicle.framework.hooks.hook_registry import HookRegistry
from chronicle.repositories.repository_types import ControlPlaneClient


@dataclass(frozen=True)
class RecordEnvironment:
    """The collaborators and policies of the record workflow."""

    service: str
    settings: SessionSettings
    hooks: HookRegistry
    """Defaults every new session inherits (copied per session)."""
    sink: EnvelopeSink | None = None
    client: ControlPlaneClient | None = None
    """Used only for synchronous trace registration."""
    trace_registration: TraceRegistration = TraceRegistration.SYNC
    registration_fail_open: bool = True
