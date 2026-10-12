"""``Crossing``: the state of one execution of a boundary (design sections 1.2 and 4.1)."""

from dataclasses import dataclass, field
from datetime import datetime

from agentplane_primitives.models import Link
from pydantic import JsonValue

from chronicle.framework.boundary_spec_types import BoundarySpec
from chronicle.framework.context.recording_session import RecordingSession
from chronicle.framework.hooks.hook_types import CallInfo
from chronicle.framework.kinds.kind_strategy_types import KindStrategy


@dataclass
class Crossing:
    """Everything the interceptor tracks between the start and the end of one call."""

    spec: BoundarySpec
    session: RecordingSession
    strategy: KindStrategy
    arguments: dict[str, JsonValue]
    """The JSON form of the bound arguments by name, before redaction."""
    info: CallInfo
    envelope_id: str
    parent_envelope_id: str | None
    started_at: datetime
    sequence: int
    invocation_index: int
    attempt: int
    links: list[Link] = field(default_factory=list)
    entered: bool = False
    """True once the ``enter`` hooks returned, so ``leave`` runs only when it should."""
    recording: bool = True
    """False in REPLAY and when recording is switched off: no envelope is written."""
