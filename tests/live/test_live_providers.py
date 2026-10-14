"""Live mode: call the real OpenAI and Anthropic APIs. Never run by default, never in CI.

These tests run only when ``CHRONICLE_LIVE=1`` is set **and** the provider key is present
(``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``). They cost a few tokens each. Run them with:

    CHRONICLE_LIVE=1 python -m pytest -m live tests/live
"""

import os

import pytest
from agentplane_primitives.models import LlmOutput

import chronicle
from tests.support.in_memory_control_plane import InMemoryControlPlane

pytestmark = pytest.mark.live

_ENABLED = os.environ.get("CHRONICLE_LIVE") == "1"


@pytest.mark.skipif(not (_ENABLED and os.environ.get("OPENAI_API_KEY")), reason="live OpenAI off")
def test_live_openai(control_plane: InMemoryControlPlane) -> None:
    import openai

    client = chronicle.wrap(openai.OpenAI())
    with chronicle.record("live-openai"):
        client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
            max_tokens=5,
        )
    chronicle.flush()
    (envelope,) = control_plane.all_envelopes()
    assert isinstance(envelope.output, LlmOutput)
    assert envelope.output.provider == "openai"
    assert envelope.output.usage is not None
    assert envelope.output.usage.input > 0


@pytest.mark.skipif(
    not (_ENABLED and os.environ.get("ANTHROPIC_API_KEY")), reason="live Anthropic off"
)
def test_live_anthropic(control_plane: InMemoryControlPlane) -> None:
    import anthropic

    client = chronicle.wrap(anthropic.Anthropic())
    with chronicle.record("live-anthropic"):
        client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=5,
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
        )
    chronicle.flush()
    (envelope,) = control_plane.all_envelopes()
    assert isinstance(envelope.output, LlmOutput)
    assert envelope.output.provider == "anthropic"
    assert envelope.output.usage is not None
    assert envelope.output.usage.input > 0
