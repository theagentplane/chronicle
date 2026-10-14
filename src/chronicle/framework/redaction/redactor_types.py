"""``Redactor``: a function from a string to a redacted string (design section 4.5)."""

from collections.abc import Callable

Redactor = Callable[[str], str]
"""A redactor maps a string to a redacted string."""

REDACTED = "[REDACTED]"
"""The mask the default redactors write in place of a secret."""
