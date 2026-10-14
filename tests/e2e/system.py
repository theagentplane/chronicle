"""Build a multi-agent system out of local servers and call it (test double, not shipped).

Every agent has its own ASGI server and its own fake LLM provider; one fake control plane
receives everything Chronicle sends. All of it runs on ephemeral localhost ports, so no test in
this suite needs network access beyond localhost.
"""

from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass, field
from typing import Any

import httpx

import chronicle
from chronicle.repositories.http_control_plane_client import INTERNAL_EXTENSION
from tests.e2e.agents.factory import ANTHROPIC_WIRE, make_agent
from tests.e2e.agents.tool_types import Tool
from tests.e2e.servers import Deferred, a2a_app, a2a_peer_tool, http_app, http_peer_tool
from tests.support.fake_control_plane_server import FakeControlPlane
from tests.support.fake_llm_server import FakeLlmServer, Scripted
from tests.support.local_server import LocalServer


@dataclass
class Node:
    """One agent: its framework, its server and its fake LLM provider."""

    name: str
    framework: str
    transport: str
    agent: Any
    server: LocalServer
    llm: FakeLlmServer
    llm_server: LocalServer

    @property
    def url(self) -> str:
        return self.server.url

    def peer_tool(self, name: str | None = None) -> Tool:
        """The tool another agent uses to call this one."""
        tool_name = name or f"ask_{self.name}"
        if self.transport == "a2a":
            return a2a_peer_tool(tool_name, self.url)
        return http_peer_tool(tool_name, self.url)


@dataclass
class System:
    """The fake control plane plus the agents added so far."""

    plane: FakeControlPlane = field(default_factory=FakeControlPlane)
    nodes: dict[str, Node] = field(default_factory=dict)
    _stack: ExitStack = field(default_factory=ExitStack)

    def __post_init__(self) -> None:
        self.plane_server = self._stack.enter_context(LocalServer(self.plane.app))

    def add(
        self,
        name: str,
        framework: str,
        script: list[Scripted],
        *,
        transport: str = "http",
        tools: list[Tool] | None = None,
        responder: Callable[[dict[str, Any]], Scripted] | None = None,
        **agent_kwargs: Any,
    ) -> Node:
        """Add an agent. Add callees before callers: a caller's tools need their URLs."""
        llm = FakeLlmServer(responder=responder)
        target = llm.anthropic_script if framework in ANTHROPIC_WIRE else llm.openai_script
        target.extend(script)
        llm_server = self._stack.enter_context(LocalServer(llm.app))
        deferred = Deferred()
        server = self._stack.enter_context(LocalServer(deferred))
        agent = make_agent(
            framework, name, llm_url=llm_server.url, tools=tools or [], **agent_kwargs
        )
        deferred.target = (
            a2a_app(agent, name, server.url) if transport == "a2a" else http_app(agent, name)
        )
        node = Node(name, framework, transport, agent, server, llm, llm_server)
        self.nodes[name] = node
        return node

    def configure(self, **settings: Any) -> None:
        """Point Chronicle at the fake control plane and allow-list the agents as peers."""
        values: dict[str, Any] = {
            "control_plane_url": self.plane_server.url,
            "inject_hosts": [n.server.host for n in self.nodes.values()],
            "batch_size": 10,
            "flush_interval": 0.05,
            "timeout": 5.0,
        }
        values.update(settings)
        chronicle.configure(**values)
        chronicle.instrument_httpx()

    def call(self, name: str, task: str, headers: dict[str, str] | None = None) -> httpx.Response:
        """Call an HTTP-transport agent from outside the system (not itself instrumented)."""
        return call_agent(self.nodes[name].url, task, headers)

    def close(self) -> None:
        chronicle.uninstrument_httpx()
        chronicle.reset()
        self._stack.close()


def call_agent(url: str, task: str, headers: dict[str, str] | None = None) -> httpx.Response:
    """POST a task to an agent. The test's own client is marked internal so it is not recorded."""
    with httpx.Client(timeout=30) as http:
        return http.post(
            f"{url}/run",
            json={"task": task},
            headers=headers or {},
            extensions={INTERNAL_EXTENSION: True},
        )
