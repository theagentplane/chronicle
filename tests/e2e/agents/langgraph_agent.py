"""LangGraph agent: an LLM node, a tool node and a routing edge, instrumented in one call.

``chronicle.instrument(graph)`` wraps every node and the routing function. The model node is a
synchronous function (LangGraph runs it in an executor thread, which exercises the
context-preserving shim) and the tool node is ``async``.
"""

import json
from typing import Annotated, Any, TypedDict

import openai
from langgraph.graph import END, StateGraph

import chronicle
from tests.e2e.agents.tool_types import SYSTEM_PROMPT, Tool


def _append(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [*left, *right]


class State(TypedDict):
    messages: Annotated[list[dict[str, Any]], _append]


class LangGraphAgent:
    """A two-node graph: ``agent`` (model) and ``tools``, with a conditional edge."""

    framework = "langgraph"

    def __init__(
        self, name: str, *, llm_url: str, tools: list[Tool], model: str = "gpt-4o"
    ) -> None:
        self.name = name
        self._model = model
        self._client = chronicle.wrap(
            openai.OpenAI(base_url=f"{llm_url}/v1", api_key="test-key", max_retries=0)
        )
        self._tool_defs = [t.openai_definition() for t in tools]
        self._tool_funcs = {t.name: t.run for t in tools}
        self._app = self._build()

    def _build(self) -> Any:
        def agent_node(state: State) -> dict[str, Any]:
            reply = self._client.chat.completions.create(
                model=self._model, messages=state["messages"], tools=self._tool_defs
            )
            return {"messages": [reply.choices[0].message.model_dump(exclude_none=True)]}

        async def tools_node(state: State) -> dict[str, Any]:
            out: list[dict[str, Any]] = []
            for call in state["messages"][-1].get("tool_calls", []):
                function = call["function"]
                try:
                    result = await self._tool_funcs[function["name"]](
                        **json.loads(function["arguments"])
                    )
                except Exception as exc:
                    result = f"error: {type(exc).__name__}: {exc}"
                out.append({"role": "tool", "tool_call_id": call["id"], "content": result})
            return {"messages": out}

        def route(state: State) -> str:
            return "tools" if state["messages"][-1].get("tool_calls") else END

        graph = StateGraph(State)
        graph.add_node("agent", agent_node)
        graph.add_node("tools", tools_node)
        graph.set_entry_point("agent")
        graph.add_conditional_edges("agent", route, {"tools": "tools", END: END})
        graph.add_edge("tools", "agent")
        return chronicle.instrument(graph).compile()

    async def run(self, task: str) -> str:
        state = await self._app.ainvoke(
            {
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": task},
                ]
            }
        )
        return str(state["messages"][-1].get("content") or "")
