"""A fake LLM provider: OpenAI Chat Completions and Anthropic Messages wire formats.

Agents point their SDK ``base_url`` at it. Responses are scripted per provider (tool calls, text,
usage with cached tokens, errors); with nothing scripted it answers with a short text. Every
request is recorded with its headers so tests can assert what did and did not cross the socket
(for example that no ``traceparent`` is sent to the provider).
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


@dataclass
class ReceivedRequest:
    path: str
    headers: dict[str, str]
    body: dict[str, Any]


@dataclass
class ErrorResponse:
    status: int
    body: dict[str, Any]


Scripted = dict[str, Any] | ErrorResponse


def openai_text(
    text: str,
    *,
    model: str = "gpt-4o-2024-08-06",
    prompt: int = 12,
    completion: int = 6,
    cached: int = 0,
) -> dict[str, Any]:
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "created": 1730000000,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text, "refusal": None},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "prompt_tokens_details": {"cached_tokens": cached},
            "completion_tokens_details": {"reasoning_tokens": 0},
        },
    }


def openai_tool_call(
    name: str, arguments: dict[str, Any], *, model: str = "gpt-4o-2024-08-06"
) -> dict[str, Any]:
    body = openai_text("", model=model)
    message = body["choices"][0]["message"]
    message["content"] = None
    message["tool_calls"] = [
        {
            "id": "call_fake1",
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)},
        }
    ]
    body["choices"][0]["finish_reason"] = "tool_calls"
    return body


def anthropic_text(
    text: str,
    *,
    model: str = "claude-sonnet-4-5-20250929",
    input_tokens: int = 12,
    output_tokens: int = 6,
    cache_read: int = 0,
) -> dict[str, Any]:
    return {
        "id": "msg_fake",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": 0,
        },
    }


def anthropic_tool_use(
    name: str, arguments: dict[str, Any], *, model: str = "claude-sonnet-4-5-20250929"
) -> dict[str, Any]:
    body = anthropic_text("", model=model)
    body["content"] = [{"type": "tool_use", "id": "toolu_fake1", "name": name, "input": arguments}]
    body["stop_reason"] = "tool_use"
    return body


@dataclass
class FakeLlmServer:
    """Holds the scripts and the request log; ``app`` is the ASGI application to serve."""

    openai_script: list[Scripted] = field(default_factory=list)
    anthropic_script: list[Scripted] = field(default_factory=list)
    requests: list[ReceivedRequest] = field(default_factory=list)
    responder: Callable[[dict[str, Any]], Scripted] | None = None
    """If set, computes each reply from the request body (for concurrent, stateless tests)."""

    @property
    def app(self) -> Starlette:
        return Starlette(
            routes=[
                Route("/v1/chat/completions", self._openai, methods=["POST"]),
                Route("/v1/messages", self._anthropic, methods=["POST"]),
            ]
        )

    async def _handle(
        self, request: Request, script: list[Scripted], default: dict[str, Any]
    ) -> JSONResponse:
        body = await request.json()
        self.requests.append(
            ReceivedRequest(
                path=request.url.path,
                headers={k.lower(): v for k, v in request.headers.items()},
                body=body,
            )
        )
        item: Scripted
        if self.responder is not None:
            item = self.responder(body)
        else:
            item = script.pop(0) if script else default
        if isinstance(item, ErrorResponse):
            return JSONResponse(item.body, status_code=item.status)
        return JSONResponse(item)

    async def _openai(self, request: Request) -> JSONResponse:
        return await self._handle(request, self.openai_script, openai_text("ok"))

    async def _anthropic(self, request: Request) -> JSONResponse:
        return await self._handle(request, self.anthropic_script, anthropic_text("ok"))
