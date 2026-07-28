#!/usr/bin/env python3
"""Reference Chronicle control plane: a shared HTTP store for deployed agents.

Deployed agents record to it with ``chronicle.record(store=RemoteStore(url))``. It keeps
envelopes in SQLite and serves them back for inspection. Zero dependency.

Run:

    python -m examples.control_plane.server --port 8900 --db control_plane.db

Endpoints:

    POST /envelopes                     store one envelope (JSON body)
    GET  /envelopes                     list all envelopes
    GET  /traces/<trace_id>/envelopes   list a trace's envelopes
    GET  /envelopes/<envelope_id>       one envelope (as a list)
    GET  /health                        {"status": "ok"}

This is a reference, not a hardened service: add auth, retention, and TLS before real
use. TokenOps can point at the same host to co-locate its cost ledger with trace storage.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from chronicle.envelope.backends import SqliteStore
from chronicle.envelope.schema import Envelope


def make_server(host: str = "127.0.0.1", port: int = 8900, db: str = ":memory:") -> ThreadingHTTPServer:
    """Build (but do not start) a control-plane server backed by a SqliteStore at ``db``."""
    store = SqliteStore(db)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload: object | None = None) -> None:
            body = json.dumps(payload).encode("utf-8") if payload is not None else b""
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _dump(self, envelopes) -> list[dict]:
            return [json.loads(e.model_dump_json()) for e in envelopes]

        def do_POST(self) -> None:
            if self.path.rstrip("/") == "/envelopes":
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                try:
                    envelope = Envelope.from_json(raw)
                except Exception as exc:  # noqa: BLE001 - report bad input, do not crash
                    self._send(400, {"error": f"invalid envelope: {exc}"})
                    return
                store.append(envelope)
                self._send(201, {"status": "stored", "envelope_id": envelope.envelope_id})
            else:
                self._send(404, {"error": "not found"})

        def do_GET(self) -> None:
            path = self.path.rstrip("/") or "/"
            if path == "/health":
                self._send(200, {"status": "ok"})
            elif path == "/envelopes":
                self._send(200, self._dump(store.read_all()))
            elif path.startswith("/traces/") and path.endswith("/envelopes"):
                trace_id = path[len("/traces/"):-len("/envelopes")]
                self._send(200, self._dump(store.find_by_trace_id(trace_id)))
            elif path.startswith("/envelopes/"):
                envelope = store.find_by_envelope_id(path[len("/envelopes/"):])
                self._send(200, self._dump([envelope] if envelope else []))
            else:
                self._send(404, {"error": "not found"})

        def log_message(self, *args) -> None:  # quiet by default
            return

    server = ThreadingHTTPServer((host, port), Handler)
    server.store = store  # type: ignore[attr-defined]
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Chronicle control plane (reference)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8900)
    parser.add_argument("--db", default="control_plane.db")
    args = parser.parse_args()

    server = make_server(args.host, args.port, args.db)
    print(f"Chronicle control plane on http://{args.host}:{args.port}  (db={args.db})")
    print("POST /envelopes | GET /envelopes | GET /traces/<id>/envelopes | GET /health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
