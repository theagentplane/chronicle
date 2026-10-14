"""Adapters: one-way translation from a provider's shape to the canonical shape (design 4.3)."""

from chronicle.framework.adapters.adapter_registry import (
    detect_provider,
    get_adapter,
    register_adapter,
)
from chronicle.framework.adapters.adapter_types import LlmAdapter
from chronicle.framework.adapters.anthropic_adapter import AnthropicAdapter
from chronicle.framework.adapters.generic_adapter import GenericLlmAdapter
from chronicle.framework.adapters.openai_adapter import OpenAiAdapter

__all__ = [
    "AnthropicAdapter",
    "GenericLlmAdapter",
    "LlmAdapter",
    "OpenAiAdapter",
    "detect_provider",
    "get_adapter",
    "register_adapter",
]
