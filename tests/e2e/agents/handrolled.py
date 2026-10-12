"""Hand-rolled agent: a plain tool-use loop calling the provider over ``httpx`` (no SDK)."""

import asyncio
import json
from typing import Any

import httpx

import chronicle
from tests.e2e.agents.tool_types import SYSTEM_PROMPT, Tool


class HandRolledAgent:
    """Speaks the OpenAI Chat Completions wire format directly.

    ``provider`` is what the agent declares itself to be: ``openai`` for the real API, or
    ``litellm`` for a LiteLLM gateway (which returns OpenAI-shaped responses).
    """

    framework = "handrolled"

    def __init__(
        self,
        name: str,
        *,
        llm_url: str,
        tools: list[Tool],
        model: str = "gpt-4o",
        provider: str = "openai",
    ) -> None:
        self.name = name
        self._llm_url = llm_url
        self._model = model
        self._tool_defs = [t.openai_definition() for t in tools]
        self._tools = {t.name: chronicle.boundary(f"tool.{t.name}")(t.run) for t in tools}
        self._chat = chronicle.wrap_llm("llm.chat", self._call_provider, provider=provider)

    async def _call_provider(
        self, model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as http:
            response = await http.post(
                f"{self._llm_url}/v1/chat/completions",
                json={"model": model, "messages": messages, "tools": tools},
                headers={"authorization": "Bearer test-key"},
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            return data

    async def run(self, task: str) -> str:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task},
        ]
        for _ in range(6):
            reply = await self._chat(self._model, messages, self._tool_defs)
            message = reply["choices"][0]["message"]
            calls = message.get("tool_calls") or []
            if not calls:
                return str(message.get("content") or "")
            messages.append(message)
            results = await asyncio.gather(*(self._run_tool(call) for call in calls))
            for call, result in zip(calls, results, strict=True):
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
        return "gave up"

    async def _run_tool(self, call: dict[str, Any]) -> str:
        function = call["function"]
        try:
            return await self._tools[function["name"]](**json.loads(function["arguments"]))
        except Exception as exc:  # the loop hands the failure to the model, as agents do
            return f"error: {type(exc).__name__}: {exc}"
