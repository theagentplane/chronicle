"""Two agents in two services: one trace across the call between them.

An orchestrator hands a question to a specialist service over HTTP. Chronicle follows the call:
the outgoing request is recorded as a tool envelope and carries the ``traceparent`` header, the
specialist joins the same trace, and its span is parented on that call. The trace is read back
from the control plane and printed as a tree.

    OPENAI_API_KEY=... python examples/multi_agent.py
"""

import json
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

import chronicle
from _support.llm import OPENAI_MODEL, openai_client
from _support.plane import LocalPlane
from _support.server import LocalApp
from _support.show import show_trace
from chronicle import ChronicleMiddleware

SPECIALIST_SYSTEM = "You are a geography specialist. Answer in one short sentence."
ORCHESTRATOR_SYSTEM = (
    "You are an orchestrator. For any factual question call ask_specialist with the question, "
    "then give the user a one-sentence final answer."
)
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "ask_specialist",
            "description": "Ask the geography specialist a question.",
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        },
    }
]


def specialist_app() -> Starlette:
    """The specialist: an HTTP service whose requests Chronicle records as their own span."""
    model = openai_client(use_async=True)

    async def answer(request: Request) -> JSONResponse:
        body = await request.json()
        reply = await model.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SPECIALIST_SYSTEM},
                {"role": "user", "content": body["question"]},
            ],
        )
        return JSONResponse({"answer": reply.choices[0].message.content})

    return Starlette(
        routes=[Route("/ask", answer, methods=["POST"])],
        middleware=[Middleware(ChronicleMiddleware, service="specialist")],
    )


def run_orchestrator(client: Any, specialist_url: str, question: str) -> str:
    """A model-and-tool loop whose one tool is an HTTP call to the specialist."""

    @chronicle.boundary("ask_specialist", kind="tool")
    def ask_specialist(question: str) -> str:
        reply = httpx.post(f"{specialist_url}/ask", json={"question": question}, timeout=60)
        reply.raise_for_status()
        return str(reply.json()["answer"])

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": ORCHESTRATOR_SYSTEM},
        {"role": "user", "content": question},
    ]
    for _ in range(4):
        reply = client.chat.completions.create(model=OPENAI_MODEL, messages=messages, tools=TOOLS)
        message = reply.choices[0].message
        if not message.tool_calls:
            return str(message.content or "")
        messages.append(message.model_dump(exclude_none=True))
        for call in message.tool_calls:
            answer = ask_specialist(**json.loads(call.function.arguments))
            messages.append({"role": "tool", "tool_call_id": call.id, "content": answer})
    return "gave up"


def main() -> None:
    client = openai_client()
    with (
        LocalApp(specialist_app()) as specialist,
        LocalPlane(service_name="orchestrator", inject_hosts=[specialist.host]) as plane,
    ):
        chronicle.instrument_httpx()  # follow calls to the hosts in inject_hosts
        try:
            with chronicle.record("multi-agent") as session:
                answer = run_orchestrator(client, specialist.url, "What is the capital of France?")
        finally:
            chronicle.uninstrument_httpx()
        print(f"answer: {answer}")
        print()
        plane.wait_for_spans(session.trace_id, 2)
        show_trace(plane, session.trace_id)
        print()
        print(
            "The specialist's span is parented on the orchestrator's outgoing call: "
            "one trace across two services."
        )


if __name__ == "__main__":
    main()
