"""Redact secrets from envelopes before they are retained, stored, or committed.

A recorded run is a faithful copy of production input and output, so it can carry
API keys, tokens, and other secrets straight into a fixture you commit to git.
Redaction runs at record time and keeps the *structure* tests assert on (message
roles, tool names, argument keys, finish reasons) while masking the *values*.

By design this ships only high-confidence secret patterns that are almost never
legitimate prompt or completion content. PII such as names and emails is context
dependent, so it is left to opt-in redactors you add yourself rather than scrubbed
by default.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from chronicle.envelope.schema import Envelope

# A redactor maps a string to a redacted string. Compose several on a session.
Redactor = Callable[[str], str]

REDACTED = "[REDACTED]"

# Shapes that are almost always secrets, safe to mask without mangling real text.
DEFAULT_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-[A-Za-z0-9]{16,}"),                       # OpenAI-style keys
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),              # Slack tokens
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),               # GitHub tokens
    re.compile(r"AKIA[0-9A-Z]{16}"),                          # AWS access key id
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}"),         # bearer tokens
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+"),  # JWTs
    re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]+?"
        r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    ),
]


def redact_secrets(patterns: list[re.Pattern[str]] | None = None) -> Redactor:
    """Return a redactor that masks high-confidence secret patterns.

    Pass your own compiled patterns to extend or replace the defaults.
    """
    pats = DEFAULT_SECRET_PATTERNS if patterns is None else patterns

    def _redact(text: str) -> str:
        for pattern in pats:
            text = pattern.sub(REDACTED, text)
        return text

    return _redact


def default_redactors() -> list[Redactor]:
    """The recommended baseline: mask common secret shapes."""
    return [redact_secrets()]


def _scrub(value: Any, redact: Redactor) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_scrub(item, redact) for item in value]
    if isinstance(value, dict):
        # Keys are structure (roles, argument names); only values are scrubbed.
        return {key: _scrub(item, redact) for key, item in value.items()}
    return value


def apply_redactors(envelope: Envelope, redactors: list[Redactor]) -> Envelope:
    """Return a copy of the envelope with every string in the input state and
    action result passed through the redactors.

    Identifiers, timestamps, and pinned metadata (model version, sampling params)
    are left intact so the record stays diagnostically useful and replayable.
    """
    if not redactors:
        return envelope

    def run(text: str) -> str:
        for redactor in redactors:
            text = redactor(text)
        return text

    data = envelope.model_dump()
    for section in ("input_state", "action_result"):
        data[section] = _scrub(data[section], run)
    return Envelope.model_validate(data)
