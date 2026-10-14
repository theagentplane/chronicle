"""``SessionSettings``: the settings a recording session needs (design sections 4.5, 4.6, 9).

The full configuration surface is in ``chronicle.config``; a session only sees the subset that
changes what it records. Building one from the full settings is the config layer's job.
"""

from dataclasses import dataclass, field

from chronicle.framework.redaction.redactor_types import Redactor


@dataclass(frozen=True)
class SessionSettings:
    """What a session honours while recording."""

    recording: bool = True
    """Master switch. ``False`` records nothing but hooks still run (design section 9)."""
    capture_input: bool = True
    capture_output: bool = True
    max_payload_bytes: int | None = None
    """Cap on the size of any one string value in a payload; ``None`` means no cap."""
    redactors: tuple[Redactor, ...] = field(default_factory=tuple)
    emit_open: bool = False
    """Send an open write for each envelope (intent capture, design section 6.3)."""
    fail_call_on_error: bool = False
    """``hooks.fail_call_on_error``: whether a hook failure fails the call."""
