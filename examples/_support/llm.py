"""Model clients for the demos. They call the real provider: a key is required.

Set ``OPENAI_API_KEY`` (and ``ANTHROPIC_API_KEY`` for the Anthropic demo). Override the model with
``DEMO_OPENAI_MODEL`` or ``DEMO_ANTHROPIC_MODEL``; point at a gateway with ``OPENAI_BASE_URL``.
"""

import os
import sys
from typing import Any

OPENAI_MODEL = os.environ.get("DEMO_OPENAI_MODEL", "gpt-4o-mini")
ANTHROPIC_MODEL = os.environ.get("DEMO_ANTHROPIC_MODEL", "claude-haiku-5-5")


def require_key(variable: str) -> None:
    """Exit with a clear message when the provider key is missing."""
    if not os.environ.get(variable):
        sys.exit(f"This demo calls a live model: set {variable} and run it again.")


def openai_client(*, use_async: bool = False) -> Any:
    """An OpenAI client wrapped by Chronicle, so every model call is recorded."""
    import openai

    import chronicle

    require_key("OPENAI_API_KEY")
    return chronicle.wrap(openai.AsyncOpenAI() if use_async else openai.OpenAI())


def anthropic_client() -> Any:
    import anthropic

    import chronicle

    require_key("ANTHROPIC_API_KEY")
    return chronicle.wrap(anthropic.Anthropic())
