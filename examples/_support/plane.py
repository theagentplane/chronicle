"""A real control plane for a demo: the ``agentplane-control-plane`` service on SQLite.

It runs inside the demo's own process on a free localhost port with a throwaway database, so a
demo needs no setup beyond ``pip install agentplane-control-plane``. What the demo saves and reads
back goes through the same HTTP API a deployed control plane serves.
"""

import gc
import shutil
import socket
import tempfile
import threading
import time
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx
import uvicorn

import chronicle
from chronicle.repositories.http_control_plane_client import INTERNAL_EXTENSION

API_KEY = "demo-key"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}


class LocalPlane:
    """Start with ``with LocalPlane() as plane:``; Chronicle is pointed at it for the block."""

    def __init__(self, **chronicle_settings: Any) -> None:
        from control_plane.api import create_app
        from control_plane.settings import Settings

        self._dir = tempfile.mkdtemp(prefix="chronicle-demo-")
        url = f"sqlite:///{(Path(self._dir) / 'plane.db').as_posix()}"
        settings = Settings(
            database_url=url, api_keys=f"{API_KEY}:demo:ingest+read", seed_on_start=False
        )
        self._app = create_app(settings)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self.port: int = self._sock.getsockname()[1]
        config = uvicorn.Config(self._app, log_level="warning", lifespan="off", access_log=False)
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=lambda: self._server.run(sockets=[self._sock]), daemon=True
        )
        self._settings = chronicle_settings

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "LocalPlane":
        self._thread.start()
        deadline = time.monotonic() + 15
        while not self._server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("the control plane did not start")
            time.sleep(0.02)
        chronicle.configure(
            control_plane_url=self.url,
            api_key=API_KEY,
            batch_size=10,
            flush_interval=0.1,
            **self._settings,
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        chronicle.flush()
        chronicle.reset()
        self._server.should_exit = True
        self._thread.join(timeout=5)
        self._sock.close()
        self._app.state.cp.engine.dispose()
        gc.collect()
        shutil.rmtree(self._dir, ignore_errors=True)

    def get(self, path: str, **params: Any) -> Any:
        """Read through the public API with the demo key (not recorded by the httpx hook)."""
        with httpx.Client(timeout=10) as http:
            response = http.get(
                f"{self.url}{path}",
                params=params,
                headers=HEADERS,
                extensions={INTERNAL_EXTENSION: True},
            )
        response.raise_for_status()
        return response.json()

    def wait_for_spans(self, trace_id: str, count: int, timeout: float = 10.0) -> dict[str, Any]:
        """Flush, then wait until ``count`` spans of the trace are closed; return the trace."""
        deadline = time.monotonic() + timeout
        while True:
            chronicle.flush()
            try:
                trace: dict[str, Any] = self.get(f"/v1/traces/{trace_id}")
            except httpx.HTTPStatusError:
                trace = {"spans": []}
            if sum(1 for s in trace["spans"] if s["state"] == "closed") >= count:
                return trace
            if time.monotonic() > deadline:
                raise RuntimeError(f"trace {trace_id} did not settle")
            time.sleep(0.05)
