"""Deletion agent test bench — simulated agent with file deletion tool."""

from __future__ import annotations

from typing import Any

from chronicle.boundary import boundary
from chronicle.envelope.schema import InputState, ToolCall

# Injectable delete implementation (ungated for record, gated for cut-point test)
_delete_impl: str = "ungated"


def set_delete_impl(mode: str) -> None:
    global _delete_impl
    if mode not in ("ungated", "gated"):
        raise ValueError("mode must be 'ungated' or 'gated'")
    _delete_impl = mode


def _ungated_delete(path: str, environment: str) -> dict[str, Any]:
    """BUG: no environment gate — allows prod deletion."""
    return {
        "status": "deleted",
        "blocked": False,
        "path": path,
        "environment": environment,
        "message": f"Deleted {path} in {environment}",
    }


def _gated_delete(path: str, environment: str) -> dict[str, Any]:
    """FIXED: block destructive operations in production."""
    if environment == "prod":
        return {
            "status": "blocked",
            "blocked": True,
            "path": path,
            "environment": environment,
            "message": f"Refused to delete {path}: production environment is protected",
        }
    return {
        "status": "deleted",
        "blocked": False,
        "path": path,
        "environment": environment,
        "message": f"Deleted {path} in {environment}",
    }


def _tool_input(*args, **kwargs) -> InputState:
    graph_state = dict(kwargs) if kwargs else {}
    if args:
        if len(args) >= 2:
            graph_state = {"path": args[0], "environment": args[1]}
        elif len(args) == 1 and isinstance(args[0], dict):
            graph_state = dict(args[0])
    return InputState(messages=[], graph_state=graph_state)


@boundary("delete_file", kind="tool", extract_input=_tool_input)
def delete_file(path: str, environment: str) -> dict[str, Any]:
    """Annotated tool boundary — same ID for record and cut-point replay."""
    impl = _gated_delete if _delete_impl == "gated" else _ungated_delete
    return impl(path, environment)


def _agent_input(*args, **kwargs) -> InputState:
    state = args[0] if args else kwargs.get("state", {})
    if not isinstance(state, dict):
        state = {}
    graph_state = dict(state)
    if len(args) > 1 and isinstance(args[1], dict):
        graph_state["tool_result"] = args[1]
    return InputState(
        messages=state.get("messages", []),
        system_prompt=state.get("system_prompt"),
        graph_state=graph_state,
    )


@boundary("agent", kind="llm", extract_input=_agent_input)
def agent_plan(state: dict[str, Any]) -> dict[str, Any]:
    """
    Simulated LLM agent — plans a prod log cleanup and emits a tool call.
    """
    tool_call = ToolCall(
        id="call_delete_1",
        name="delete_file",
        arguments={
            "path": "/prod/logs/app.log",
            "environment": state.get("environment", "prod"),
        },
    )
    return {
        **state,
        "tool_calls": [tool_call.model_dump()],
        "completion": "I'll delete the old production log file now.",
        "finish_reason": "tool_calls",
    }


@boundary("agent", kind="llm", extract_input=_agent_input)
def agent_finalize(state: dict[str, Any], tool_result: dict[str, Any]) -> dict[str, Any]:
    """Simulated LLM — confirms outcome to the user."""
    if tool_result.get("blocked"):
        completion = (
            "I attempted the deletion but the operation was blocked "
            f"by environment policy: {tool_result['message']}"
        )
    elif tool_result.get("status") == "deleted":
        completion = f"Done. {tool_result['message']}"
    else:
        completion = f"Tool returned: {tool_result}"

    return {
        **state,
        "tool_result": tool_result,
        "tool_calls": [],
        "completion": completion,
        "finish_reason": "stop",
        "deleted": tool_result.get("status") == "deleted",
        "blocked": tool_result.get("blocked", False),
    }


def run_deletion_agent(
    *,
    user_message: str,
    environment: str = "prod",
    system_prompt: str = "You are an ops assistant that manages log files.",
) -> dict[str, Any]:
    """Run the full deletion scenario through annotated boundaries."""
    state: dict[str, Any] = {
        "messages": [{"role": "user", "content": user_message}],
        "user_message": user_message,
        "system_prompt": system_prompt,
        "environment": environment,
        "tool_calls": [],
        "completion": "",
        "finish_reason": "",
        "deleted": False,
        "blocked": False,
    }

    state = agent_plan(state)

    tool_result: dict[str, Any] = {}
    for tc in state.get("tool_calls", []):
        if tc["name"] == "delete_file":
            args = tc["arguments"]
            tool_result = delete_file(args["path"], args["environment"])

    return agent_finalize(state, tool_result)
