"""OpenAI SDK agent: a Chat Completions tool loop using the ``openai`` package."""

import asyncio
import json
from typing import Any

import openai

import chronicle
from tests.e2e.agents.tool_types import SYSTEM_PROMPT, Tool


class OpenAiSdkAgent:
    """Tool loop over ``openai.AsyncOpenAI``, wrapped with ``chronicle.wrap``."""

    framework = "openai_sdk"

    def __init__(
        self, name: str, *, llm_url: str, tools: list[Tool], model: str = "gpt-4o"
    ) -> None:
        self.name = name
        self._model = model
        self._client = chronicle.wrap(
            openai.AsyncOpenAI(base_url=f"{llm_url}/v1", api_key="test-key", max_retries=0)
        )
        self._tool_defs = [t.openai_definition() for t in tools]
        self._tools = {t.name: chronicle.boundary(f"tool.{t.name}")(t.run) for t in tools}

    async def run(self, task: str) -> str:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task},
        ]
        for _ in range(6):
            reply = await self._client.chat.completions.create(
                model=self._model, messages=messages, tools=self._tool_defs
            )
            message = reply.choices[0].message
            if not message.tool_calls:
                return message.content or ""
            messages.append(message.model_dump(exclude_none=True))
            results = await asyncio.gather(*(self._run_tool(call) for call in message.tool_calls))
            for call, result in zip(message.tool_calls, results, strict=True):
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
        return "gave up"

    async def _run_tool(self, call: Any) -> str:
        try:
            return await self._tools[call.function.name](**json.loads(call.function.arguments))
        except Exception as exc:
            return f"error: {type(exc).__name__}: {exc}"
