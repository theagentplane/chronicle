"""Serve an ASGI app on a free localhost port in a background thread (a demo's second agent)."""

import socket
import threading
import time
from types import TracebackType
from typing import Any

import uvicorn


class LocalApp:
    """``with LocalApp(app) as server:`` then call ``server.url``."""

    def __init__(self, app: Any) -> None:
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

    def __enter__(self) -> "LocalApp":
        self._thread.start()
        deadline = time.monotonic() + 15
        while not self._server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("the demo server did not start")
            time.sleep(0.02)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5)
        self._sock.close()
