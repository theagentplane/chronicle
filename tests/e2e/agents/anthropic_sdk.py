"""Claude SDK agent: the Anthropic SDK tool-use loop (``anthropic`` package).

"Claude SDK" is read here as the Anthropic API SDK. The Claude Agent SDK drives the Claude Code
CLI as a subprocess and cannot run offline against a fake provider, so it is not covered.
"""

import asyncio
from typing import Any

import anthropic

import chronicle
from tests.e2e.agents.tool_types import SYSTEM_PROMPT, Tool


class AnthropicSdkAgent:
    """Tool loop over ``anthropic.AsyncAnthropic``, wrapped with ``chronicle.wrap``."""

    framework = "anthropic_sdk"

    def __init__(
        self, name: str, *, llm_url: str, tools: list[Tool], model: str = "claude-sonnet-5-5"
    ) -> None:
        self.name = name
        self._model = model
        self._client = chronicle.wrap(
            anthropic.AsyncAnthropic(base_url=llm_url, api_key="test-key", max_retries=0)
        )
        self._tool_defs = [t.anthropic_definition() for t in tools]
        self._tools = {t.name: chronicle.boundary(f"tool.{t.name}")(t.run) for t in tools}

    async def run(self, task: str) -> str:
        messages: list[dict[str, Any]] = [{"role": "user", "content": task}]
        for _ in range(6):
            reply = await self._client.messages.create(
                model=self._model,
                max_tokens=512,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=self._tool_defs,
            )
            uses = [block for block in reply.content if block.type == "tool_use"]
            if not uses:
                return "".join(b.text for b in reply.content if b.type == "text")
            messages.append(
                {"role": "assistant", "content": [b.model_dump() for b in reply.content]}
            )
            results = await asyncio.gather(*(self._run_tool(use) for use in uses))
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": use.id, "content": result}
                        for use, result in zip(uses, results, strict=True)
                    ],
                }
            )
        return "gave up"

    async def _run_tool(self, use: Any) -> str:
        try:
            return await self._tools[use.name](**use.input)
        except Exception as exc:
            return f"error: {type(exc).__name__}: {exc}"
