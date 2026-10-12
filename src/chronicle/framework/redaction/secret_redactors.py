"""The default redactors: mask common secret shapes (design section 4.5).

Only high-confidence patterns that are almost never legitimate prompt or completion content ship
by default. Pattern-based redaction is a baseline, not a guarantee; PII such as names and emails
is context dependent and needs redactors you add yourself.
"""

import re

from chronicle.framework.redaction.redactor_types import REDACTED, Redactor

DEFAULT_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),  # OpenAI and Anthropic style keys
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),  # Slack tokens
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),  # GitHub tokens
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key id
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}"),  # bearer tokens
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+"),  # JWTs
    re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]+?"
        r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    ),
)


def redact_secrets(patterns: tuple[re.Pattern[str], ...] | None = None) -> Redactor:
    """Return a redactor that masks the given secret patterns (the defaults if ``None``)."""
    chosen = DEFAULT_SECRET_PATTERNS if patterns is None else patterns

    def _redact(text: str) -> str:
        for pattern in chosen:
            text = pattern.sub(REDACTED, text)
        return text

    return _redact


def default_redactors() -> list[Redactor]:
    """The recommended baseline: mask common secret shapes."""
    return [redact_secrets()]
