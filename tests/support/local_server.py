"""Run an ASGI app on an ephemeral localhost port in a background thread (test double).

Used so that headers really cross a socket: the fake LLM provider, the fake control plane and
the agents of the end-to-end suite are all served this way. Nothing leaves localhost.
"""

import socket
import threading
import time
from types import TracebackType
from typing import Any

import uvicorn


class LocalServer:
    """A uvicorn server on ``127.0.0.1`` with an OS-assigned port."""

    def __init__(self, app: Any) -> None:
        # Bind the socket ourselves so the port is known before the server starts.
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self.port: int = self._sock.getsockname()[1]
        config = uvicorn.Config(app, log_level="warning", lifespan="off", access_log=False)
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=lambda: self._server.run(sockets=[self._sock]), daemon=True
        )

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def host(self) -> str:
        return f"127.0.0.1:{self.port}"

    def start(self) -> "LocalServer":
        self._thread.start()
        deadline = time.monotonic() + 10
        while not self._server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("local test server did not start")
            time.sleep(0.01)
        return self

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5)
        self._sock.close()

    def __enter__(self) -> "LocalServer":
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()
