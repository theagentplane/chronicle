"""Agents as ASGI apps, each with the Chronicle middleware, over plain HTTP or A2A.

Both are served on ephemeral localhost ports (see ``tests/support/local_server.py``) so headers
really cross a socket. The A2A variant uses the ``a2a-sdk`` server and client unchanged: the
``httpx`` instrumenter and the ASGI middleware cover it with no A2A-specific code.
"""

from typing import Any

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.helpers.proto_helpers import get_message_text, new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue_v2 import EventQueue  # type: ignore[attr-defined]
from a2a.server.request_handlers import DefaultRequestHandlerV2
from a2a.server.routes import create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types.a2a_pb2 import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    Role,
    SendMessageRequest,
)
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

import chronicle
from tests.e2e.agents.tool_types import Tool


class Deferred:
    """An ASGI app whose target is set after the port is known."""

    def __init__(self) -> None:
        self.target: Any = None

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        await self.target(scope, receive, send)


def http_app(agent: Any, service: str) -> Any:
    """``POST /run {"task": ...}`` -> ``{"answer": ...}``."""

    async def run(request: Request) -> JSONResponse:
        body = await request.json()
        return JSONResponse({"answer": await agent.run(body["task"])})

    app = Starlette(routes=[Route("/run", run, methods=["POST"])])
    return chronicle.ChronicleMiddleware(app, service=service)


class _AgentExecutor(AgentExecutor):
    def __init__(self, agent: Any) -> None:
        self._agent = agent

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        text = get_message_text(context.message) if context.message else ""
        answer = await self._agent.run(text)
        await event_queue.enqueue_event(new_text_message(answer))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return None


def _card(name: str, base_url: str) -> AgentCard:
    return AgentCard(
        name=name,
        description=f"{name} test agent",
        version="1.0",
        supported_interfaces=[
            AgentInterface(
                url=f"{base_url}/rpc", protocol_binding="JSONRPC", protocol_version="1.0"
            )
        ],
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
    )


def a2a_app(agent: Any, service: str, base_url: str) -> Any:
    """An A2A JSON-RPC server (``a2a-sdk``) for ``agent``."""
    handler = DefaultRequestHandlerV2(
        agent_executor=_AgentExecutor(agent),
        task_store=InMemoryTaskStore(),
        agent_card=_card(service, base_url),
    )
    app = Starlette(routes=create_jsonrpc_routes(handler, "/rpc"))
    return chronicle.ChronicleMiddleware(app, service=service)


def http_peer_tool(name: str, base_url: str) -> Tool:
    """A tool that delegates to another agent over plain HTTP with ``httpx``."""

    async def ask(task: str) -> str:
        async with httpx.AsyncClient(timeout=20) as http:
            response = await http.post(f"{base_url}/run", json={"task": task})
            response.raise_for_status()
            return str(response.json()["answer"])

    return Tool(name=name, description=f"Ask the {name} agent over HTTP", run=ask)


def a2a_peer_tool(name: str, base_url: str) -> Tool:
    """A tool that delegates to another agent through the A2A protocol (``a2a-sdk`` client)."""

    async def ask(task: str) -> str:
        async with httpx.AsyncClient(timeout=20) as http:
            factory = ClientFactory(ClientConfig(httpx_client=http, streaming=False))
            client = factory.create(_card(name, base_url))
            request = SendMessageRequest(message=new_text_message(task, role=Role.ROLE_USER))
            async for event in client.send_message(request):
                if event.HasField("message"):
                    return get_message_text(event.message)
        return ""

    return Tool(name=name, description=f"Ask the {name} agent over A2A", run=ask)
