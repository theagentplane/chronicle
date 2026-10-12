"""LangChain agent: a chat model with tools and an agent-executor style loop.

LangChain's ``ChatOpenAI`` uses the ``openai`` SDK underneath; its ``async_client`` resource is
wrapped with ``chronicle.wrap`` so the model call is recorded with the same canonical fields as
every other framework.
"""

import asyncio
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

import chronicle
from tests.e2e.agents.tool_types import SYSTEM_PROMPT, Tool


class LangChainAgent:
    """Tool loop over ``ChatOpenAI.bind_tools``."""

    framework = "langchain"

    def __init__(
        self, name: str, *, llm_url: str, tools: list[Tool], model: str = "gpt-4o"
    ) -> None:
        self.name = name
        chat = ChatOpenAI(  # type: ignore[call-arg]
            model=model,
            base_url=f"{llm_url}/v1",
            api_key="test-key",
            max_retries=0,
            use_responses_api=False,
        )
        chronicle.wrap(chat.async_client)
        self._model = chat.bind_tools([t.openai_definition() for t in tools])
        self._tools = {t.name: chronicle.boundary(f"tool.{t.name}")(t.run) for t in tools}

    async def run(self, task: str) -> str:
        messages: list[BaseMessage] = [SystemMessage(SYSTEM_PROMPT), HumanMessage(task)]
        for _ in range(6):
            reply = await self._model.ainvoke(messages)
            if not reply.tool_calls:
                return str(reply.content)
            messages.append(reply)
            results = await asyncio.gather(*(self._run_tool(call) for call in reply.tool_calls))
            for call, result in zip(reply.tool_calls, results, strict=True):
                messages.append(ToolMessage(content=result, tool_call_id=call["id"]))
        return "gave up"

    async def _run_tool(self, call: Any) -> str:
        try:
            return await self._tools[call["name"]](**call["args"])
        except Exception as exc:
            return f"error: {type(exc).__name__}: {exc}"
