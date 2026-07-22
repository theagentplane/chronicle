"""Model metadata capture on the @boundary record path.

These pin the fidelity promise from the README's Envelope table: the recorded
envelope should reflect the model version and sampling parameters the call
actually used, not a session placeholder.
"""

from __future__ import annotations

import pytest

from chronicle import boundary, reset_session


@pytest.mark.layer1
def test_llm_boundary_captures_model_and_sampling():
    @boundary("planner", kind="llm")
    def planner(state: dict) -> dict:
        return {
            "completion": "ok",
            "finish_reason": "stop",
            "model": "gpt-4o-2024-08-06",
            "temperature": 0.2,
            "max_tokens": 256,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

    session = reset_session()
    session.begin_trace("t-meta")
    planner({"messages": [{"role": "user", "content": "hi"}]})

    env = session._recorded_envelopes[-1]
    assert env.metadata.model_version == "gpt-4o-2024-08-06"
    assert env.metadata.sampling_params.temperature == 0.2
    assert env.metadata.sampling_params.max_tokens == 256
    assert env.action_result.token_usage == {"input_tokens": 10, "output_tokens": 5}


@pytest.mark.layer1
def test_nested_sampling_params_are_captured():
    @boundary("planner", kind="llm")
    def planner(state: dict) -> dict:
        return {
            "completion": "ok",
            "model_version": "claude-sonnet-4-6",
            "sampling_params": {"temperature": 0.0, "top_p": 0.9, "seed": 7},
        }

    session = reset_session()
    session.begin_trace("t-nested")
    planner({"messages": []})

    sp = session._recorded_envelopes[-1].metadata.sampling_params
    assert (sp.temperature, sp.top_p, sp.seed) == (0.0, 0.9, 7)


@pytest.mark.layer1
def test_falls_back_to_session_default_when_unspecified():
    @boundary("planner", kind="llm")
    def planner(state: dict) -> dict:
        return {"completion": "ok", "finish_reason": "stop"}

    session = reset_session()
    session.model_version = "claude-sonnet-4-6"  # user-pinned default
    session.begin_trace("t-default")
    planner({"messages": []})

    assert session._recorded_envelopes[-1].metadata.model_version == "claude-sonnet-4-6"


@pytest.mark.layer1
def test_default_model_version_is_honest_placeholder():
    # Never silently claim a fake pinned version like the old "demo-model".
    assert reset_session().model_version == "unknown"


@pytest.mark.layer1
def test_tool_boundary_is_not_mislabeled_with_model():
    # A tool result that happens to carry a "model" key must not become the
    # envelope's model_version — only llm boundaries carry model metadata.
    @boundary("lookup", kind="tool")
    def lookup(path: str) -> dict:
        return {"status": "ok", "model": "not-a-model-version"}

    session = reset_session()
    session.begin_trace("t-tool")
    lookup("/x")

    assert session._recorded_envelopes[-1].metadata.model_version == "unknown"


@pytest.mark.layer1
def test_extract_metadata_hook_overrides():
    @boundary(
        "planner",
        kind="llm",
        extract_metadata=lambda r: {"model_version": r["meta"]["m"], "temperature": 0.7},
    )
    def planner(state: dict) -> dict:
        return {"completion": "ok", "meta": {"m": "gpt-4o-mini"}}

    session = reset_session()
    session.begin_trace("t-hook")
    planner({"messages": []})

    env = session._recorded_envelopes[-1]
    assert env.metadata.model_version == "gpt-4o-mini"
    assert env.metadata.sampling_params.temperature == 0.7
