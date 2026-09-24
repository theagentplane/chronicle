"""Per-provider adapters: normalize any LLM API into Chronicle's neutral shapes.

Think of each provider (OpenAI, Anthropic, ...) as speaking a different language.
An adapter is a translator with two jobs:

- ``parse_request(kwargs)``: read the call arguments (where is the system prompt?
  where are messages? which model?) and return a neutral ``LLMRequest`` plus a
  list of typed ``Message`` objects.
- ``parse_response(response)``: read the SDK response (where is the text? tool
  calls? finish reason? token counts?) and return a neutral ``LLMOutput`` plus
  the model name the response reports (or None).

Rules every adapter follows:

- Duck-typing only: read attributes AND dict keys, never ``import openai``.
  That keeps provider SDKs optional.
- Never raise: on anything unknown/malformed, return empty shapes. Recording
  must never break the agent call.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol

from chronicle.envelope.genai import LLMRequest, SamplingParams
from chronicle.envelope.schema import LLMOutput, Message, Usage


class Provider(Protocol):
    """Translator for one LLM API."""

    name: str

    def parse_request(self, kwargs: Mapping[str, Any]) -> tuple[LLMRequest, list[Message]]:
        """Normalize call arguments into (request, messages)."""
        ...

    def parse_response(self, response: Any) -> tuple[LLMOutput, str | None]:
        """Normalize an SDK response into (output, response_model)."""
        ...


_REGISTRY: dict[str, Provider] = {}


def register_provider(provider: Provider) -> Provider:
    """Add (or replace) an adapter so users can support another API."""
    _REGISTRY[provider.name] = provider
    return provider


def get_provider(name: str | None) -> Provider:
    """Look up an adapter; unknown/missing names fall back to generic."""
    if name is not None and name in _REGISTRY:
        return _REGISTRY[name]
    from chronicle.providers.generic import GenericProvider

    return _REGISTRY.setdefault("generic", GenericProvider())


def provider_names() -> list[str]:
    return sorted(_REGISTRY)


# --------------------------------------------------------------------------- #
# Shared tiny helpers (all never-raise, all duck-typed)
# --------------------------------------------------------------------------- #


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump()
        except Exception:
            return None
        return dumped if isinstance(dumped, Mapping) else None
    data = getattr(value, "__dict__", None)
    return data if isinstance(data, Mapping) else None


def get_field(obj: Any, key: str, default: Any = None) -> Any:
    """Read ``obj.key`` OR ``obj[key]`` (SDK objects and plain dicts both work)."""
    if isinstance(obj, Mapping) and key in obj:
        return obj[key]
    value = getattr(obj, key, None)
    return default if value is None else value


def get_path(obj: Any, *keys: Any) -> Any:
    """Walk attributes/keys/indexes safely; return None on any miss."""
    current = obj
    for key in keys:
        if current is None:
            return None
        try:
            if isinstance(key, int):
                current = current[key] if isinstance(current, (list, tuple)) else None
            else:
                current = get_field(current, key)
        except (AttributeError, IndexError, KeyError, TypeError):
            return None
    return current


def coerce_tool_arguments(raw: Any) -> dict[str, Any]:
    """Tool args arrive as a JSON string (OpenAI) or a dict (Anthropic)."""
    if raw is None:
        return {}
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    return {}


def coerce_messages(rows: Any) -> list[Message]:
    out: list[Message] = []
    if not isinstance(rows, (list, tuple)):
        return out
    for row in rows:
        if isinstance(row, Mapping):
            try:
                out.append(Message.model_construct(**{"role": "", "content": None, **dict(row)}))
            except Exception:
                continue
        elif isinstance(row, str):
            out.append(Message.model_construct(role="user", content=row))
    return out


def coerce_usage(raw: Any) -> Usage | None:
    """Accept every known usage key shape; keep only integral counts."""
    from chronicle.session import usage_from

    if raw is None:
        return None
    mapping = _as_mapping(raw)
    if mapping is None:
        return None
    # Normalize camelCase / Gemini names to the snake_case keys usage_from knows,
    # plus the snake_case keys it already handles.
    aliased: dict[str, Any] = dict(mapping)
    aliases = {
        "inputTokens": "input_tokens",
        "outputTokens": "output_tokens",
        "promptTokenCount": "input_tokens",
        "candidatesTokenCount": "output_tokens",
        "prompt_tokens": "input_tokens",
        "completion_tokens": "output_tokens",
    }
    for src, dst in aliases.items():
        if dst not in aliased and src in aliased:
            aliased[dst] = aliased[src]
    try:
        return usage_from(aliased)
    except Exception:
        return None


def base_request(
    kwargs: Mapping[str, Any],
    provider: str,
    *,
    model_keys: tuple[str, ...] = ("model",),
) -> LLMRequest:
    """Build an LLMRequest from common sampling keys + model keys. Never raises."""
    from chronicle.envelope.genai import model_from, sampling_params_from

    try:
        model: str | None = None
        for key in model_keys:
            value = kwargs.get(key)
            if value:
                model = str(value)
                break
        if model is None:
            model = model_from(kwargs)
        sampling = sampling_params_from(kwargs) or SamplingParams()
        return LLMRequest(model=model, provider=provider, sampling=sampling)
    except Exception:
        return LLMRequest(provider=provider)


def _register_builtins() -> None:
    from chronicle.providers import anthropic as _anthropic
    from chronicle.providers import generic as _generic
    from chronicle.providers import openai_chat as _openai_chat
    from chronicle.providers import openai_responses as _responses

    for mod in (_generic, _openai_chat, _anthropic, _responses):
        for cls_name in (
            "GenericProvider",
            "OpenAIChatProvider",
            "AnthropicProvider",
            "OpenAIResponsesProvider",
        ):
            cls = getattr(mod, cls_name, None)
            if cls is not None:
                try:
                    register_provider(cls())
                except Exception:
                    pass


_register_builtins()
