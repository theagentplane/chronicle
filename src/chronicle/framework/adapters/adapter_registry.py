"""Adapter lookup by provider and provider detection from a client (design section 4.3).

Adapters are looked up by provider id. For LLMs the provider is detected from the client type or
given explicitly. A new provider is a new adapter registered here, with no change to the kind
registry or the strategies. With no match the generic adapter is used: ``provider = unknown`` and
``usage = null``.
"""

from typing import Any

from agentplane_primitives.types import UNKNOWN_PROVIDER

from chronicle.framework.adapters.adapter_types import LlmAdapter
from chronicle.framework.adapters.anthropic_adapter import AnthropicAdapter
from chronicle.framework.adapters.generic_adapter import GenericLlmAdapter
from chronicle.framework.adapters.openai_adapter import OpenAiAdapter

_ADAPTERS: dict[str, LlmAdapter] = {
    "openai": OpenAiAdapter("openai"),
    "azure": OpenAiAdapter("azure"),
    "litellm": OpenAiAdapter("litellm"),
    "anthropic": AnthropicAdapter(),
}
_GENERIC = GenericLlmAdapter()


def register_adapter(adapter: LlmAdapter) -> None:
    """Register ``adapter`` under its ``provider``, replacing any earlier one."""
    _ADAPTERS[adapter.provider] = adapter


def get_adapter(provider: str | None) -> LlmAdapter:
    """Return the adapter for ``provider``, or the generic adapter if there is none."""
    if provider is None:
        return _GENERIC
    return _ADAPTERS.get(provider, _GENERIC)


def detect_provider(client: Any) -> str:
    """Return the provider id for an SDK client, from its type (``unknown`` if not recognised)."""
    cls = type(client)
    module = (cls.__module__ or "").split(".")[0].lower()
    if module == "openai":
        return "azure" if "azure" in cls.__name__.lower() else "openai"
    if module == "anthropic":
        return "anthropic"
    if module == "litellm":
        return "litellm"
    return UNKNOWN_PROVIDER
