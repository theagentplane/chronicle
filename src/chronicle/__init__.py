"""Chronicle: record what an agent did, save it to the control plane, replay a request.

Chronicle is an edge component: it runs inside the agent's own process and does no storage or
viewing. The entities (``Trace``, ``Span``, ``Envelope``) come from ``agentplane-primitives``.
See ``docs/rfcs/chronicle-technical-design.md`` for the design.
"""

from chronicle._version import __version__
from chronicle.capabilities.replay.replay_plan_types import ReplayPlan
from chronicle.capabilities.replay.replay_state import CallRecord
from chronicle.capabilities.replay.replayer import ReplayRun
from chronicle.framework.boundary_enums import BoundaryMode, SessionMode
from chronicle.framework.context.attempt_utils import attempt
from chronicle.framework.context.recording_session import RecordingSession
from chronicle.framework.errors import RecordedCallError, ReplayMismatchError
from chronicle.framework.hooks.hook_registry import HookRegistry, default_hooks
from chronicle.framework.hooks.hook_types import AbortCall, CallInfo, FunctionHook, Hook
from chronicle.framework.redaction.secret_redactors import default_redactors, redact_secrets
from chronicle.interfaces import (
    ChronicleMiddleware,
    aspan,
    boundary,
    configure,
    current_session,
    extract,
    flush,
    inject,
    instrument,
    instrument_httpx,
    instrument_langgraph,
    is_enabled,
    record,
    replay,
    replay_trace,
    reset,
    shutdown,
    span,
    uninstrument_httpx,
    wrap,
    wrap_llm,
)
from chronicle.repositories.errors import ControlPlaneError, DeliveryError, RegistrationError

__all__ = [
    "AbortCall",
    "BoundaryMode",
    "CallInfo",
    "CallRecord",
    "ChronicleMiddleware",
    "ControlPlaneError",
    "DeliveryError",
    "FunctionHook",
    "Hook",
    "HookRegistry",
    "RecordedCallError",
    "RecordingSession",
    "RegistrationError",
    "ReplayMismatchError",
    "ReplayPlan",
    "ReplayRun",
    "SessionMode",
    "__version__",
    "aspan",
    "attempt",
    "boundary",
    "configure",
    "current_session",
    "default_hooks",
    "default_redactors",
    "extract",
    "flush",
    "inject",
    "instrument",
    "instrument_httpx",
    "instrument_langgraph",
    "is_enabled",
    "record",
    "redact_secrets",
    "replay",
    "replay_trace",
    "reset",
    "shutdown",
    "span",
    "uninstrument_httpx",
    "wrap",
    "wrap_llm",
]
