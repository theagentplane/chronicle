"""The same agent in four frameworks, recorded the same way.

One small task (a weather lookup through a tool) is run with the OpenAI SDK, the Anthropic SDK,
LangChain and LangGraph. Each wires Chronicle in with one or two lines (marked ``# chronicle``).
The control plane then holds one trace per run, and the model call is described with the same
canonical fields whatever the framework or provider.

    OPENAI_API_KEY=... ANTHROPIC_API_KEY=... python examples/frameworks.py [openai anthropic ...]

Frameworks whose key is missing are skipped.
"""

import json
import os
import sys
from collections.abc import Callable
from typing import Any, TypedDict

import chronicle
from _support.llm import ANTHROPIC_MODEL, OPENAI_MODEL
from _support.plane import LocalPlane

TASK = "What is the weather in Lisbon? Use the tool, then answer in one sentence."
SCHEMA = {
    "type": "object",
    "properties": {"city": {"type": "string"}},
    "required": ["city"],
}


@chronicle.boundary("get_weather", kind="tool")  # chronicle: records the tool call
def get_weather(city: str) -> dict[str, Any]:
    return {"city": city, "forecast": "sunny", "temperature_c": 24}


def openai_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": "get_weather", "description": "Weather.", "parameters": SCHEMA},
    }


def run_openai() -> str:
    import openai

    client = chronicle.wrap(openai.OpenAI())  # chronicle: every model call is recorded
    messages: list[dict[str, Any]] = [{"role": "user", "content": TASK}]
    for _ in range(4):
        reply = client.chat.completions.create(
            model=OPENAI_MODEL, messages=messages, tools=[openai_tool()]
        )
        message = reply.choices[0].message
        if not message.tool_calls:
            return str(message.content)
        messages.append(message.model_dump(exclude_none=True))
        for call in message.tool_calls:
            result = get_weather(**json.loads(call.function.arguments))
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)}
            )
    return "gave up"


def run_anthropic() -> str:
    import anthropic

    client = chronicle.wrap(anthropic.Anthropic())  # chronicle: every model call is recorded
    tools = [{"name": "get_weather", "description": "Weather.", "input_schema": SCHEMA}]
    messages: list[dict[str, Any]] = [{"role": "user", "content": TASK}]
    for _ in range(4):
        reply = client.messages.create(
            model=ANTHROPIC_MODEL, max_tokens=300, messages=messages, tools=tools
        )
        uses = [b for b in reply.content if b.type == "tool_use"]
        if not uses:
            return "".join(b.text for b in reply.content if b.type == "text")
        messages.append({"role": "assistant", "content": [b.model_dump() for b in reply.content]})
        results = [
            {
                "type": "tool_result",
                "tool_use_id": use.id,
                "content": json.dumps(get_weather(**use.input)),
            }
            for use in uses
        ]
        messages.append({"role": "user", "content": results})
    return "gave up"


def run_langchain() -> str:
    from langchain_core.messages import HumanMessage, ToolMessage
    from langchain_openai import ChatOpenAI

    chat = ChatOpenAI(model=OPENAI_MODEL, use_responses_api=False)  # type: ignore[call-arg]
    chronicle.wrap(chat.client)  # chronicle: the SDK resource LangChain calls underneath
    model = chat.bind_tools([openai_tool()])
    messages: list[Any] = [HumanMessage(TASK)]
    for _ in range(4):
        reply = model.invoke(messages)
        if not reply.tool_calls:
            return str(reply.content)
        messages.append(reply)
        for call in reply.tool_calls:
            result = get_weather(**call["args"])
            messages.append(ToolMessage(content=json.dumps(result), tool_call_id=call["id"]))
    return "gave up"


def run_langgraph() -> str:
    import openai
    from langgraph.graph import END, StateGraph

    client = chronicle.wrap(openai.OpenAI())  # chronicle: the model call

    class State(TypedDict):
        messages: list[dict[str, Any]]

    def agent(state: State) -> dict[str, Any]:
        reply = client.chat.completions.create(
            model=OPENAI_MODEL, messages=state["messages"], tools=[openai_tool()]
        )
        message = reply.choices[0].message.model_dump(exclude_none=True)
        return {"messages": [*state["messages"], message]}

    def tools(state: State) -> dict[str, Any]:
        out = list(state["messages"])
        for call in out[-1]["tool_calls"]:
            result = get_weather(**json.loads(call["function"]["arguments"]))
            out.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)})
        return {"messages": out}

    def route(state: State) -> str:
        return "tools" if state["messages"][-1].get("tool_calls") else END

    graph = StateGraph(State)
    graph.add_node("agent", agent)
    graph.add_node("tools", tools)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", route, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    app = chronicle.instrument(graph).compile()  # chronicle: every node and the router
    final = app.invoke({"messages": [{"role": "user", "content": TASK}]})
    return str(final["messages"][-1].get("content"))


RUNNERS: dict[str, tuple[str, Callable[[], str]]] = {
    "openai": ("OPENAI_API_KEY", run_openai),
    "anthropic": ("ANTHROPIC_API_KEY", run_anthropic),
    "langchain": ("OPENAI_API_KEY", run_langchain),
    "langgraph": ("OPENAI_API_KEY", run_langgraph),
}


def main() -> None:
    chosen = sys.argv[1:] or list(RUNNERS)
    with LocalPlane() as plane:
        rows: list[tuple[str, str, str, str, str]] = []
        for name in chosen:
            key, runner = RUNNERS[name]
            if not os.environ.get(key):
                print(f"skipping {name}: {key} is not set")
                continue
            with chronicle.record(name, service=name) as session:
                answer = runner()
            trace = plane.wait_for_spans(session.trace_id, 1)
            span_id = trace["spans"][0]["span_id"]
            envelopes = plane.get(f"/v1/traces/{session.trace_id}/spans/{span_id}/envelopes")
            llm = [e for e in envelopes["envelopes"] if e["kind"] == "llm"]
            tools = [e for e in envelopes["envelopes"] if e["kind"] == "tool"]
            first = llm[0]["output"]
            usage = first["usage"]
            rows.append(
                (
                    name,
                    f"{len(llm)} llm / {len(tools)} tool",
                    f"{first['provider']} {first['model']}",
                    f"{usage['input']} in / {usage['output']} out",
                    answer[:40].replace("\n", " "),
                )
            )
        print(
            f"\n{'framework':<10} {'envelopes':<16} {'provider and model':<40} {'first call':<18}"
        )
        for name, counts, model, tokens, answer in rows:
            print(f"{name:<10} {counts:<16} {model:<40} {tokens:<18} {answer!r}")


if __name__ == "__main__":
    main()
