"""Provider conformance, client layer: the real SDKs against a local fake provider (4.3).

The real ``openai`` and ``anthropic`` clients (sync and async) call a local fake HTTP server via
``base_url`` and are wrapped with ``wrap(client)``. Asserted: provider detection from the client
type, the recorded envelope, and that the return value and the exceptions are untouched.
"""

import asyncio
from collections.abc import Iterator
from typing import Any

import anthropic
import openai
import pytest
from agentplane_primitives.enums import ModelSource, Status
from agentplane_primitives.models import LlmInput, LlmOutput, ToolCallBlock

import chronicle
from tests.support.fake_llm_server import (
    ErrorResponse,
    FakeLlmServer,
    anthropic_text,
    anthropic_tool_use,
    openai_text,
    openai_tool_call,
)
from tests.support.in_memory_control_plane import InMemoryControlPlane
from tests.support.local_server import LocalServer


@pytest.fixture
def llm() -> Iterator[tuple[FakeLlmServer, LocalServer]]:
    fake = FakeLlmServer()
    with LocalServer(fake.app) as server:
        yield fake, server


def _only_llm_envelope(plane: InMemoryControlPlane) -> tuple[LlmInput, LlmOutput, Any]:
    chronicle.flush()
    (envelope,) = plane.all_envelopes()
    assert isinstance(envelope.input, LlmInput)
    assert isinstance(envelope.output, LlmOutput)
    return envelope.input, envelope.output, envelope


def test_openai_sync(
    llm: tuple[FakeLlmServer, LocalServer], control_plane: InMemoryControlPlane
) -> None:
    fake, server = llm
    fake.openai_script.append(openai_text("Hi there", prompt=40, completion=5, cached=16))
    client = chronicle.wrap(openai.OpenAI(base_url=f"{server.url}/v1", api_key="k", max_retries=0))

    with chronicle.record("job"):
        response = client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": "hello"}], temperature=0.1
        )

    assert isinstance(response, openai.types.chat.ChatCompletion)  # the real object, untouched
    assert response.choices[0].message.content == "Hi there"
    llm_input, output, envelope = _only_llm_envelope(control_plane)
    assert envelope.metadata["client.library"] == "openai"
    assert envelope.metadata["client.base_url"] == f"{server.url}/v1/"
    assert llm_input.model == "gpt-4o"
    assert llm_input.params.temperature == 0.1
    assert output.provider == "openai"
    assert output.model == "gpt-4o-2024-08-06"
    assert output.model_source is ModelSource.SERVED
    assert output.usage is not None
    assert (output.usage.input, output.usage.cached_read, output.usage.output) == (24, 16, 5)
    assert isinstance(output.raw, dict)
    assert output.raw["id"] == "chatcmpl-fake"  # the provider's response, stored unchanged


def test_openai_async(
    llm: tuple[FakeLlmServer, LocalServer], control_plane: InMemoryControlPlane
) -> None:
    fake, server = llm
    fake.openai_script.append(openai_tool_call("get_weather", {"city": "Paris"}))

    async def main() -> Any:
        client = chronicle.wrap(
            openai.AsyncOpenAI(base_url=f"{server.url}/v1", api_key="k", max_retries=0)
        )
        async with chronicle.aspan():
            return await client.chat.completions.create(
                model="gpt-4o", messages=[{"role": "user", "content": "weather?"}]
            )

    response = asyncio.run(main())
    assert response.choices[0].message.tool_calls[0].function.name == "get_weather"
    _, output, _ = _only_llm_envelope(control_plane)
    assert output.provider == "openai"
    call = output.content[0]
    assert isinstance(call, ToolCallBlock)
    assert call.arguments == {"city": "Paris"}


def test_anthropic_sync(
    llm: tuple[FakeLlmServer, LocalServer], control_plane: InMemoryControlPlane
) -> None:
    fake, server = llm
    fake.anthropic_script.append(anthropic_text("Bonjour", input_tokens=9, output_tokens=3))
    client = chronicle.wrap(anthropic.Anthropic(base_url=server.url, api_key="k", max_retries=0))

    with chronicle.record("job"):
        message = client.messages.create(
            model="claude-sonnet-5-5",
            max_tokens=50,
            system="be brief",
            messages=[{"role": "user", "content": "hi"}],
        )

    assert isinstance(message, anthropic.types.Message)
    assert message.content[0].text == "Bonjour"  # type: ignore[union-attr]
    llm_input, output, envelope = _only_llm_envelope(control_plane)
    assert envelope.metadata["client.library"] == "anthropic"
    assert llm_input.system == "be brief"
    assert llm_input.params.max_tokens == 50
    assert output.provider == "anthropic"
    assert output.usage is not None
    assert (output.usage.input, output.usage.output) == (9, 3)


def test_anthropic_async(
    llm: tuple[FakeLlmServer, LocalServer], control_plane: InMemoryControlPlane
) -> None:
    fake, server = llm
    fake.anthropic_script.append(anthropic_tool_use("search", {"q": "cats"}))

    async def main() -> Any:
        client = chronicle.wrap(
            anthropic.AsyncAnthropic(base_url=server.url, api_key="k", max_retries=0)
        )
        async with chronicle.aspan():
            return await client.messages.create(
                model="claude-sonnet-5-5",
                max_tokens=50,
                messages=[{"role": "user", "content": "find cats"}],
            )

    message = asyncio.run(main())
    assert message.stop_reason == "tool_use"
    _, output, _ = _only_llm_envelope(control_plane)
    assert output.provider == "anthropic"
    assert output.content[0].type == "tool_call"


@pytest.mark.parametrize("which", ["openai", "anthropic"])
def test_a_provider_error_is_recorded_and_reraised_untouched(
    llm: tuple[FakeLlmServer, LocalServer], control_plane: InMemoryControlPlane, which: str
) -> None:
    fake, server = llm
    if which == "openai":
        fake.openai_script.append(
            ErrorResponse(429, {"error": {"message": "slow down", "type": "rate_limit_error"}})
        )
        client: Any = chronicle.wrap(
            openai.OpenAI(base_url=f"{server.url}/v1", api_key="k", max_retries=0)
        )

        def call() -> Any:
            return client.chat.completions.create(
                model="gpt-4o", messages=[{"role": "user", "content": "x"}]
            )

        expected: type[Exception] = openai.RateLimitError
    else:
        fake.anthropic_script.append(
            ErrorResponse(
                429,
                {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}},
            )
        )
        client = chronicle.wrap(
            anthropic.Anthropic(base_url=server.url, api_key="k", max_retries=0)
        )

        def call() -> Any:
            return client.messages.create(
                model="claude-sonnet-5-5",
                max_tokens=5,
                messages=[{"role": "user", "content": "x"}],
            )

        expected = anthropic.RateLimitError

    with pytest.raises(expected), chronicle.record("job"):
        call()

    chronicle.flush()
    (envelope,) = control_plane.all_envelopes()
    assert envelope.envelope_status.status is Status.FAILURE
    assert isinstance(envelope.output, LlmOutput)
    assert envelope.output.error is not None
    assert envelope.output.error.type == "RateLimitError"
    # a failed call has only the error
    assert envelope.output.content == []
    assert envelope.output.usage is None
    assert envelope.output.finish_reason is None


def test_an_openai_shaped_litellm_response(
    llm: tuple[FakeLlmServer, LocalServer], control_plane: InMemoryControlPlane
) -> None:
    fake, server = llm
    fake.openai_script.append(openai_text("via litellm", model="azure/gpt-4o-2024-08-06"))
    client = chronicle.wrap(
        openai.OpenAI(base_url=f"{server.url}/v1", api_key="k", max_retries=0), provider="litellm"
    )
    with chronicle.record("job"):
        client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": "x"}])
    _, output, _ = _only_llm_envelope(control_plane)
    assert output.provider == "litellm"
    assert output.model == "azure/gpt-4o-2024-08-06"
    assert output.usage is not None


def test_an_unknown_client_has_unknown_provider_and_null_usage(
    control_plane: InMemoryControlPlane,
) -> None:
    class Completions:
        def create(self, **kwargs: Any) -> dict[str, Any]:
            return openai_text("hello from nowhere")

    class Chat:
        completions = Completions()

    class HomeGrownClient:
        chat = Chat()

    client = chronicle.wrap(HomeGrownClient())
    with chronicle.record("job"):
        result = client.chat.completions.create(model="m", messages=[])
    assert result["choices"][0]["message"]["content"] == "hello from nowhere"
    _, output, _ = _only_llm_envelope(control_plane)
    assert output.provider == "unknown"
    assert output.usage is None
    assert isinstance(output.raw, dict)  # raw is still stored


def test_streaming_is_not_supported_and_goes_straight_through(
    control_plane: InMemoryControlPlane,
) -> None:
    class Completions:
        def create(self, **kwargs: Any) -> str:
            return "a stream object"

    class Chat:
        completions = Completions()

    class Client:
        chat = Chat()

    client = chronicle.wrap(Client())
    with chronicle.record("job"):
        assert client.chat.completions.create(model="m", messages=[], stream=True) == (
            "a stream object"
        )
    chronicle.flush()
    assert control_plane.all_envelopes() == []  # documented: streaming is not recorded


def test_replay_stub_makes_no_api_call(
    llm: tuple[FakeLlmServer, LocalServer], control_plane: InMemoryControlPlane
) -> None:
    fake, server = llm
    fake.openai_script.append(openai_text("recorded answer"))
    client = chronicle.wrap(openai.OpenAI(base_url=f"{server.url}/v1", api_key="k", max_retries=0))
    with chronicle.record("job") as session:
        client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": "x"}])
    chronicle.flush()
    assert len(fake.requests) == 1

    with chronicle.replay_trace(session.trace_id, session.span_id, client=control_plane):
        replayed = client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": "x"}]
        )
    assert replayed.choices[0].message.content == "recorded answer"
    assert len(fake.requests) == 1  # no second HTTP request


def test_the_sdks_use_an_instrumentable_http_library() -> None:
    """The ``httpx`` instrumenter patches ``httpx`` and ``httpx2``; the SDKs use one of them."""
    from chronicle.interfaces.httpx_instrumenter import SUPPORTED_MODULES

    for sdk_client in (openai.OpenAI(api_key="k"), anthropic.Anthropic(api_key="k")):
        library = type(sdk_client._client).__mro__[-3].__module__.split(".")[0]
        assert library in SUPPORTED_MODULES
