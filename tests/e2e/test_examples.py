"""The demos in ``examples/`` run end to end against the real control plane.

The demos call a live model. Here the model is a scripted local server reached through
``OPENAI_BASE_URL``, so the whole path (agent, Chronicle, control plane, replay) is exercised
without a key or a network. Skipped when the control-plane package is not installed.
"""

import runpy
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from tests.support.fake_llm_server import FakeLlmServer, openai_text, openai_tool_call
from tests.support.local_server import LocalServer

pytest.importorskip("control_plane", reason="install the control-plane package to run these")

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeLlmServer]:
    llm = FakeLlmServer()
    server = LocalServer(llm.app).start()
    monkeypatch.setenv("OPENAI_BASE_URL", f"{server.url}/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.syspath_prepend(str(EXAMPLES))
    try:
        yield llm
    finally:
        server.stop()


@pytest.fixture
def run_demo(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    def run(name: str, *argv: str) -> None:
        monkeypatch.setattr(sys, "argv", [name, *argv])
        runpy.run_path(str(EXAMPLES / name), run_name="__main__")

    return run


def test_record_and_replay_blocks_the_recorded_call(
    model: FakeLlmServer, run_demo: Callable[..., None], capsys: pytest.CaptureFixture[str]
) -> None:
    model.openai_script += [
        openai_tool_call("delete_file", {"path": "/var/log/app/app.log", "environment": "prod"}),
        openai_text("Deleted the log."),
    ]
    run_demo("record_and_replay.py")

    out = capsys.readouterr().out
    assert "deleted:    ['prod:/var/log/app/app.log']" in out
    assert "tool result: {'blocked': True" in out
    assert len(model.requests) == 2  # the replay made no model call


def test_multi_agent_prints_one_trace_across_two_services(
    model: FakeLlmServer, run_demo: Callable[..., None], capsys: pytest.CaptureFixture[str]
) -> None:
    model.openai_script += [
        openai_tool_call("ask_specialist", {"question": "capital of France?"}),
        openai_text("Paris."),  # the specialist
        openai_text("The capital is Paris."),  # the orchestrator
    ]
    run_demo("multi_agent.py")

    out = capsys.readouterr().out
    assert "service=orchestrator" in out
    assert "service=specialist" in out
    assert out.index("http POST") < out.index("service=specialist")  # nested under the call


def test_every_incident_is_recorded_and_the_fix_holds(
    model: FakeLlmServer, run_demo: Callable[..., None], capsys: pytest.CaptureFixture[str]
) -> None:
    model.openai_script += [openai_text("Done.")] * 6
    run_demo("incidents.py")

    out = capsys.readouterr().out
    assert out.count("PASS") == 6
    assert "FAIL" not in out
    assert len(model.requests) == 6  # one live message per incident, none on replay


def test_the_frameworks_demo_records_each_one_the_same_way(
    model: FakeLlmServer, run_demo: Callable[..., None], capsys: pytest.CaptureFixture[str]
) -> None:
    for _ in range(3):  # openai, langchain, langgraph (anthropic is skipped without a key)
        model.openai_script += [
            openai_tool_call("get_weather", {"city": "Lisbon"}),
            openai_text("Sunny and 24 degrees."),
        ]
    run_demo("frameworks.py")

    out = capsys.readouterr().out
    assert "skipping anthropic" in out
    for name in ("openai", "langchain", "langgraph"):
        assert f"\n{name} " in out
    assert out.count("2 llm / 1 tool") >= 2
