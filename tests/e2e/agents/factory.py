"""Build an agent of a named framework."""

from typing import Any

from tests.e2e.agents.anthropic_sdk import AnthropicSdkAgent
from tests.e2e.agents.handrolled import HandRolledAgent
from tests.e2e.agents.langchain_agent import LangChainAgent
from tests.e2e.agents.langgraph_agent import LangGraphAgent
from tests.e2e.agents.openai_sdk import OpenAiSdkAgent
from tests.e2e.agents.tool_types import Tool

FRAMEWORKS = ["handrolled", "langchain", "langgraph", "anthropic_sdk", "openai_sdk"]

ANTHROPIC_WIRE = {"anthropic_sdk"}
"""Frameworks whose model calls speak the Anthropic Messages wire format."""


def make_agent(framework: str, name: str, *, llm_url: str, tools: list[Tool], **kwargs: Any) -> Any:
    """Return an agent object with ``name``, ``framework`` and ``async run(task) -> str``."""
    classes: dict[str, Any] = {
        "handrolled": HandRolledAgent,
        "langchain": LangChainAgent,
        "langgraph": LangGraphAgent,
        "anthropic_sdk": AnthropicSdkAgent,
        "openai_sdk": OpenAiSdkAgent,
    }
    return classes[framework](name, llm_url=llm_url, tools=tools, **kwargs)
