"""The same multi-agent systems against the **real** control plane, not the fake.

The control-plane service (``control_plane`` package, SQLite) is started in this process on an
ephemeral port with an API key, and Chronicle saves to it and replays from it over HTTP. Skipped
when the package is not installed. Run it with the control-plane checkout installed:

    uv pip install -e ../control-plane
    python -m pytest -m e2e tests/e2e/test_real_control_plane.py

Chronicle's own HTTP client does all the talking; the test reads back through the control plane's
public API with the same bearer key, so what is asserted is what a real deployment would hold.
"""

import asyncio
import gc
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from agentplane_primitives.models import Envelope, LlmOutput

import chronicle
from chronicle import ReplayPlan
from chronicle.repositories import HttpControlPlaneClient
from chronicle.repositories.http_control_plane_client import INTERNAL_EXTENSION
from tests.e2e.scripts import delegate_then_answer, final
from tests.e2e.system import System
from tests.support.local_server import LocalServer

pytest.importorskip("control_plane", reason="install the control-plane package to run these")

from control_plane.api import create_app
from control_plane.settings import Settings

API_KEY = "chronicle-e2e-key"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}


class RealPlane:
    """A running control-plane service and a reader for its public API."""

    def __init__(self) -> None:
        self._dir = tempfile.mkdtemp()
        url = f"sqlite:///{(Path(self._dir) / 'plane.db').as_posix()}"
        self._app = create_app(
            Settings(database_url=url, api_keys=f"{API_KEY}:acme:ingest+read", seed_on_start=False)
        )
        self.server = LocalServer(self._app).start()
        self.url = self.server.url

    def get(self, path: str, **params: Any) -> Any:
        with httpx.Client(timeout=10) as http:
            response = http.request(
                "GET",
                f"{self.url}{path}",
                params=params,
                headers=HEADERS,
                extensions={INTERNAL_EXTENSION: True},
            )
        response.raise_for_status()
        return response.json()

    def settle(self, spans: int, timeout: float = 10.0) -> str:
        """Wait until ``spans`` spans of one trace are closed; return the trace id."""
        import time

        deadline = time.monotonic() + timeout
        while True:
            chronicle.flush()
            traces = self.get("/v1/traces")["traces"]
            if len(traces) == 1:
                detail = self.get(f"/v1/traces/{traces[0]['trace_id']}")
                closed = [s for s in detail["spans"] if s["state"] == "closed"]
                if len(closed) == spans:
                    return str(traces[0]["trace_id"])
            if time.monotonic() > deadline:
                raise AssertionError(f"traces never settled: {traces}")
            time.sleep(0.05)

    def close(self) -> None:
        self.server.stop()
        self._app.state.cp.engine.dispose()
        gc.collect()
        shutil.rmtree(self._dir, ignore_errors=True)


@pytest.fixture
def plane() -> Iterator[RealPlane]:
    real = RealPlane()
    try:
        yield real
    finally:
        real.close()


def _chain(system: System, plane: RealPlane, **settings: Any) -> Any:
    specialist = system.add("specialist", "handrolled", [final("handrolled", "paris")])
    orchestrator = system.add(
        "orchestrator",
        "openai_sdk",
        delegate_then_answer("openai_sdk", "ask_specialist", "capital of France?", "It is Paris."),
        tools=[specialist.peer_tool("ask_specialist")],
    )
    system.configure(control_plane_url=plane.url, api_key=API_KEY, **settings)
    return orchestrator, specialist


def test_a_chain_is_saved_to_the_real_control_plane(system: System, plane: RealPlane) -> None:
    orchestrator, _specialist = _chain(system, plane)

    assert system.call("orchestrator", "capital of France?").json() == {"answer": "It is Paris."}

    trace_id = plane.settle(spans=2)
    trace = plane.get(f"/v1/traces/{trace_id}")
    assert trace["state"] == "closed"  # derived: no span is open
    spans = {s["service"]: s for s in trace["spans"]}
    assert set(spans) == {"orchestrator", "specialist"}
    assert {s["status"] for s in spans.values()} == {"success"}

    mine = [
        Envelope.model_validate(e)  # the control plane serves valid primitives envelopes
        for e in plane.get(
            f"/v1/traces/{trace_id}/spans/{spans['orchestrator']['span_id']}/envelopes"
        )["envelopes"]
    ]
    outbound = next(e for e in mine if e.name.startswith("http POST"))
    assert spans["specialist"]["parent_envelope_id"] == outbound.envelope_id
    llm = [e for e in mine if e.name == "llm"]  # chronicle.wrap names the boundary "llm"
    assert len(llm) == 2
    assert isinstance(llm[0].output, LlmOutput)
    assert llm[0].output.provider == "openai"
    assert llm[0].output.usage is not None
    assert orchestrator.llm.requests  # the agent really ran


def test_replay_reads_the_span_back_from_the_real_control_plane(
    system: System, plane: RealPlane
) -> None:
    orchestrator, specialist = _chain(system, plane)
    system.call("orchestrator", "capital of France?")
    trace_id = plane.settle(spans=2)
    span_id = next(
        s["span_id"]
        for s in plane.get(f"/v1/traces/{trace_id}")["spans"]
        if s["service"] == "orchestrator"
    )
    llm_calls, peer_calls = len(orchestrator.llm.requests), len(specialist.llm.requests)

    client = HttpControlPlaneClient(plane.url, api_key=API_KEY)
    with chronicle.replay_trace(trace_id, span_id, client=client) as run:
        answer = asyncio.run(orchestrator.agent.run("capital of France?"))
    assert answer == "It is Paris."
    assert (len(orchestrator.llm.requests), len(specialist.llm.requests)) == (llm_calls, peer_calls)
    assert run.invocation_count("llm") == 2

    plan = ReplayPlan().run("tool.ask_specialist", 1)
    with chronicle.replay_trace(trace_id, span_id, plan, client=client) as run:
        asyncio.run(orchestrator.agent.run("capital of France?"))
    assert run.captured_result("tool.ask_specialist", 1) == "paris"
    client.close()


def test_open_then_close_is_one_record_on_the_real_control_plane(
    system: System, plane: RealPlane
) -> None:
    _chain(system, plane, emit_open=True)
    system.call("orchestrator", "capital of France?")
    trace_id = plane.settle(spans=2)

    spans = plane.get(f"/v1/traces/{trace_id}")["spans"]
    for span in spans:
        envelopes = plane.get(f"/v1/traces/{trace_id}/spans/{span['span_id']}/envelopes")
        assert envelopes["envelopes"]
        assert {e["envelope_status"]["state"] for e in envelopes["envelopes"]} == {"closed"}
        ids = [e["envelope_id"] for e in envelopes["envelopes"]]
        assert len(ids) == len(set(ids))  # the open write was replaced, not duplicated


def test_trace_labels_are_written_once(plane: RealPlane) -> None:
    chronicle.configure(
        control_plane_url=plane.url, api_key=API_KEY, batch_size=1, flush_interval=0.01
    )

    @chronicle.boundary("step")
    def step() -> int:
        return 1

    with chronicle.record("checkout", labels={"session_id": "s-42", "user_id": "u1"}) as session:
        step()
    chronicle.flush()
    chronicle.reset()

    found = plane.get("/v1/traces", session_id="s-42")["traces"]
    assert [t["trace_id"] for t in found] == [session.trace_id]
    detail = plane.get(f"/v1/traces/{session.trace_id}")
    assert detail["name"] == "checkout"
    assert detail["metadata"] == {"session_id": "s-42", "user_id": "u1"}
    assert detail["state"] == "closed"


def test_a_wrong_api_key_fails_open_and_strict(system: System, plane: RealPlane) -> None:
    _chain(system, plane)
    system.configure(control_plane_url=plane.url, api_key="wrong-key")

    # fail-open (default): the agents still work, nothing is stored
    assert system.call("orchestrator", "capital of France?").json() == {"answer": "It is Paris."}
    chronicle.flush()
    assert plane.get("/v1/traces")["traces"] == []

    # strict: the control plane's 401 fails the request
    system.configure(
        control_plane_url=plane.url,
        api_key="wrong-key",
        registration_fail_open=False,
        fail_open=False,
    )
    assert system.call("orchestrator", "capital of France?").status_code == 500
