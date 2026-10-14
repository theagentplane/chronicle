"""``wrap(client)``: record every model call an SDK client makes (design sections 4.1, 4.3).

    client = chronicle.wrap(OpenAI())
    client.chat.completions.create(model="gpt-4o", messages=[...])  # recorded

The client's completion method is wrapped in place and the client is returned. The provider is
detected from the client type (OpenAI, Azure OpenAI, Anthropic, LiteLLM) or given with
``provider=``; an unknown client gives ``provider = unknown`` and ``usage = null``. The wrapper
is transparent in RECORD; in REPLAY a STUB returns the recorded response with attribute access
and makes no API call.

**Streaming is not supported** (design section 6.5): a call with ``stream=True`` goes straight to
the SDK and is not recorded.
"""

import contextlib
import functools
import importlib.metadata
import inspect
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from agentplane_primitives.enums import Kind
from pydantic import JsonValue

from chronicle.framework.adapters.adapter_registry import detect_provider
from chronicle.framework.adapters.adapter_types import LlmAdapter
from chronicle.interfaces.boundary_api import make_spec
from chronicle.interfaces.runtime_utils import interceptor

_DEFAULT_HOSTS = {"api.openai.com", "api.anthropic.com"}
_FLAG = "_chronicle_wrapped"


def wrap(
    client: Any,
    *,
    name: str = "llm",
    provider: str | None = None,
    adapter: LlmAdapter | None = None,
) -> Any:
    """Wrap an OpenAI- or Anthropic-style client in place and return it."""
    target = _completion_target(client)
    if target is None:
        raise TypeError(
            "chronicle.wrap expected an OpenAI-style client (.chat.completions.create), an "
            "Anthropic-style client (.messages.create) or a completions resource (.create). "
            "Use wrap_llm for other callables."
        )
    owner, attr, original = target
    if getattr(original, _FLAG, False):
        return client
    resolved = provider or detect_provider(client)
    spec = make_spec(
        original,
        name,
        Kind.LLM,
        provider=resolved,
        adapter=adapter,
        metadata=_client_metadata(client),
    )
    setattr(owner, attr, _wrapped(original, spec))
    return client


def _completion_target(client: Any) -> tuple[Any, str, Callable[..., Any]] | None:
    completions = getattr(getattr(client, "chat", None), "completions", None)
    if completions is not None and callable(getattr(completions, "create", None)):
        return completions, "create", completions.create
    messages = getattr(client, "messages", None)
    if messages is not None and callable(getattr(messages, "create", None)):
        return messages, "create", messages.create
    # A resource object that already is the completions or messages endpoint, for example the
    # ``client`` and ``async_client`` attributes of LangChain's ChatOpenAI.
    if callable(getattr(client, "create", None)):
        return client, "create", client.create
    return None


def _wrapped(create: Callable[..., Any], spec: Any) -> Callable[..., Any]:
    if _is_async(create):

        @functools.wraps(create)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            if kwargs.get("stream"):
                return await create(*args, **kwargs)
            return await interceptor.acall(spec, create, args, kwargs)

        setattr(async_wrapper, _FLAG, True)
        return async_wrapper

    @functools.wraps(create)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("stream"):
            return create(*args, **kwargs)
        return interceptor.call(spec, create, args, kwargs)

    setattr(wrapper, _FLAG, True)
    return wrapper


def _is_async(create: Callable[..., Any]) -> bool:
    """True if ``create`` is a coroutine function, also through ``functools.wraps`` layers.

    SDK methods are decorated (argument checks, overloads), so the outermost callable may look
    synchronous while the function it wraps is ``async def``.
    """
    if inspect.iscoroutinefunction(create):
        return True
    try:
        return inspect.iscoroutinefunction(inspect.unwrap(create))
    except ValueError:  # a cycle in __wrapped__
        return False


def _client_metadata(client: Any) -> dict[str, JsonValue]:
    """Static client identity only (design 2.3): library, version and a non-default base URL."""
    metadata: dict[str, JsonValue] = {}
    library = (type(client).__module__ or "").split(".")[0]
    if library:
        metadata["client.library"] = library
        with contextlib.suppress(importlib.metadata.PackageNotFoundError):
            metadata["client.version"] = importlib.metadata.version(library)
    base_url = getattr(client, "base_url", None)
    if base_url is not None:
        parts = urlsplit(str(base_url))
        if parts.hostname and parts.hostname not in _DEFAULT_HOSTS:
            # Credentials embedded in the URL (user:password@host) are not recorded.
            netloc = parts.hostname + (f":{parts.port}" if parts.port else "")
            metadata["client.base_url"] = f"{parts.scheme}://{netloc}{parts.path}"
    return metadata
