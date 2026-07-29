"""Storage backends for envelopes.

Every backend satisfies the ``Store`` protocol, so `chronicle.record(store=...)` and
`session.store` accept any of them and nothing downstream changes.

- ``JsonlStore`` (the default ``EnvelopeStore``): append-only JSONL on local disk.
  Zero config, perfect for local development and CI fixtures.
- ``SqliteStore``: durable, queryable SQLite. Zero dependency (stdlib ``sqlite3``).
  A good fit for a single deployed agent instance.
- ``RemoteStore``: ships envelopes to a Chronicle control plane over HTTP. Point many
  deployed agents at one shared service (which TokenOps can also write to). Uses stdlib
  ``urllib`` and never raises into the agent: a failed append is warned and dropped, so
  recording can never break production.

Pick one with ``open_store(target)``:

    open_store("runs.jsonl")                 # JsonlStore  (local file)
    open_store("sqlite:///runs.db")          # SqliteStore (deployed instance)
    open_store("https://chronicle.internal") # RemoteStore (shared control plane)
"""

from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.request
import warnings
from pathlib import Path
from typing import Protocol, runtime_checkable

from chronicle.envelope.schema import Envelope
from chronicle.envelope.store import EnvelopeStore

# The local JSONL store is the default backend; expose it under the backend name too.
JsonlStore = EnvelopeStore


@runtime_checkable
class Store(Protocol):
    """What a recording backend must provide. ``EnvelopeStore`` already satisfies it."""

    def append(self, envelope: Envelope) -> None: ...
    def read_all(self) -> list[Envelope]: ...
    def find_by_trace_id(self, trace_id: str) -> list[Envelope]: ...
    def find_by_envelope_id(self, envelope_id: str) -> Envelope | None: ...


class SqliteStore:
    """Append-only envelope store backed by SQLite (stdlib, zero dependency).

    Durable and queryable with no files to hand-manage. Safe for concurrent appends
    from multiple threads (async requests share one store); writes are serialized with a
    lock and the connection allows cross-thread use.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS envelopes ("
            "envelope_id TEXT PRIMARY KEY, trace_id TEXT, sequence INTEGER, data TEXT)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trace ON envelopes (trace_id, sequence)"
        )
        self._conn.commit()

    def append(self, envelope: Envelope) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO envelopes (envelope_id, trace_id, sequence, data) "
                "VALUES (?, ?, ?, ?)",
                (envelope.envelope_id, envelope.trace_id, envelope.sequence,
                 envelope.model_dump_json()),
            )
            self._conn.commit()

    def read_all(self) -> list[Envelope]:
        rows = self._conn.execute(
            "SELECT data FROM envelopes ORDER BY sequence, envelope_id"
        ).fetchall()
        return [Envelope.from_json(r[0]) for r in rows]

    def find_by_trace_id(self, trace_id: str) -> list[Envelope]:
        rows = self._conn.execute(
            "SELECT data FROM envelopes WHERE trace_id = ? ORDER BY sequence, envelope_id",
            (trace_id,),
        ).fetchall()
        return [Envelope.from_json(r[0]) for r in rows]

    def find_by_envelope_id(self, envelope_id: str) -> Envelope | None:
        row = self._conn.execute(
            "SELECT data FROM envelopes WHERE envelope_id = ?", (envelope_id,)
        ).fetchone()
        return Envelope.from_json(row[0]) if row else None

    def close(self) -> None:
        self._conn.close()


class RemoteStore:
    """Ships envelopes to a Chronicle control plane over HTTP (stdlib ``urllib``).

    Point deployed agents at one shared service. Recording must never break the agent,
    so a failed append is warned and dropped rather than raised. Reads return an empty
    list on failure. See ``examples/control_plane/server.py`` for a reference service.
    """

    def __init__(self, base_url: str, *, api_key: str | None = None, timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def append(self, envelope: Envelope) -> None:
        request = urllib.request.Request(
            f"{self.base_url}/envelopes",
            data=envelope.model_dump_json().encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=self.timeout).read()
        except (urllib.error.URLError, OSError) as exc:
            warnings.warn(f"chronicle RemoteStore append dropped: {exc}", stacklevel=2)

    def read_all(self) -> list[Envelope]:
        return self._get("/envelopes")

    def find_by_trace_id(self, trace_id: str) -> list[Envelope]:
        return self._get(f"/traces/{trace_id}/envelopes")

    def find_by_envelope_id(self, envelope_id: str) -> Envelope | None:
        found = self._get(f"/envelopes/{envelope_id}")
        return found[0] if found else None

    def _get(self, path: str) -> list[Envelope]:
        request = urllib.request.Request(f"{self.base_url}{path}", headers=self._headers())
        try:
            body = urllib.request.urlopen(request, timeout=self.timeout).read()
        except (urllib.error.URLError, OSError):
            return []
        payload = json.loads(body)
        items = payload if isinstance(payload, list) else [payload]
        return [Envelope.from_json(json.dumps(item)) for item in items]


def open_store(target: str | Path, **kwargs) -> Store:
    """Build a store from a target string. See module docstring for the forms.

    - ``http(s)://...``            -> RemoteStore (control plane), accepts api_key/timeout
    - ``sqlite:///path`` or ``*.db`` / ``*.sqlite`` -> SqliteStore
    - anything else                -> JsonlStore (local file, the default)
    """
    text = str(target)
    if text.startswith(("http://", "https://")):
        return RemoteStore(text, **kwargs)
    if text.startswith("sqlite:///"):
        return SqliteStore(text[len("sqlite:///"):], **kwargs)
    if text.endswith((".db", ".sqlite")):
        return SqliteStore(text, **kwargs)
    return JsonlStore(text)
