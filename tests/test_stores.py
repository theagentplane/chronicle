"""Storage backends: SQLite and Remote satisfy the Store protocol, round-trip
envelopes, and drive chronicle.record. open_store dispatches by target string, and a
RemoteStore talks to the reference control-plane server end to end.
"""

from __future__ import annotations

import threading
import warnings

import chronicle
from chronicle import (
    BufferedStore,
    EnvelopeStore,
    JsonlStore,
    RemoteStore,
    SqliteStore,
    Store,
    boundary,
    open_store,
)
from chronicle.envelope.schema import ActionResult, ContextMetadata, Envelope, InputState
from examples.control_plane.server import make_server


def _env(trace_id: str, seq: int, node: str = "agent") -> Envelope:
    return Envelope(
        node_id=node,
        boundary_kind="tool",
        trace_id=trace_id,
        sequence=seq,
        metadata=ContextMetadata(model_version="m", build_id="b"),
        input_state=InputState(messages=[]),
        action_result=ActionResult(completion=f"ok-{seq}"),
    )


def test_sqlite_roundtrip(tmp_path):
    store = SqliteStore(tmp_path / "runs.db")
    a, b, c = _env("t1", 1), _env("t1", 2), _env("t2", 1)
    for e in (a, b, c):
        store.append(e)
    assert len(store.read_all()) == 3
    assert [e.sequence for e in store.find_by_trace_id("t1")] == [1, 2]
    assert store.find_by_envelope_id(a.envelope_id).action_result.completion == "ok-1"
    assert store.find_by_envelope_id("missing") is None
    store.close()


def test_backends_satisfy_store_protocol(tmp_path):
    assert isinstance(SqliteStore(":memory:"), Store)
    assert isinstance(JsonlStore(tmp_path / "r.jsonl"), Store)
    assert isinstance(RemoteStore("http://localhost:1"), Store)
    assert isinstance(BufferedStore(JsonlStore(tmp_path / "b.jsonl")), Store)


def test_open_store_dispatch(tmp_path):
    assert isinstance(open_store(tmp_path / "r.jsonl"), EnvelopeStore)
    assert isinstance(open_store(str(tmp_path / "r.db")), SqliteStore)
    assert isinstance(open_store("sqlite:///" + str(tmp_path / "x.db")), SqliteStore)
    assert isinstance(open_store("https://cp.example"), RemoteStore)
    buffered = open_store(f"buffered:8:{tmp_path / 'buf.jsonl'}")
    assert isinstance(buffered, BufferedStore)
    assert buffered.batch_size == 8


def test_buffered_store_batches_jsonl_flush(tmp_path):
    path = tmp_path / "runs.jsonl"
    store = BufferedStore(JsonlStore(path), batch_size=3)
    store.append(_env("t", 1))
    store.append(_env("t", 2))
    assert path.read_text(encoding="utf-8").strip() == ""  # still buffered
    store.append(_env("t", 3))  # hits batch_size -> flush
    assert len(JsonlStore(path).read_all()) == 3
    store.append(_env("t", 4))
    store.flush()
    assert len(store.read_all()) == 4


def test_record_into_sqlite(tmp_path):
    store = SqliteStore(tmp_path / "runs.db")

    with chronicle.record("t-rec", store=store):

        @boundary("agent", kind="tool")
        def do(x):
            return {"ok": x}

        do(1)

    assert len(store.find_by_trace_id("t-rec")) == 1
    store.close()


def test_record_with_sqlite_url_string(tmp_path):
    url = "sqlite:///" + str(tmp_path / "u.db")
    with chronicle.record("t-url", store=url):

        @boundary("agent", kind="tool")
        def do(x):
            return {"ok": x}

        do(1)

    assert len(open_store(url).find_by_trace_id("t-url")) == 1


def test_remote_store_end_to_end():
    server = make_server("127.0.0.1", 0)  # port 0 -> ephemeral
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        store = RemoteStore(f"http://127.0.0.1:{port}")
        a, b = _env("rt", 1), _env("rt", 2)
        store.append(a)
        store.append(b)
        assert [e.sequence for e in store.find_by_trace_id("rt")] == [1, 2]
        assert len(store.read_all()) == 2
        one = store.find_by_envelope_id(a.envelope_id)
        assert one is not None and one.envelope_id == a.envelope_id
        assert store.find_by_envelope_id("missing") is None
    finally:
        server.shutdown()


def test_remote_store_append_never_raises_the_agent():
    store = RemoteStore("http://127.0.0.1:1", timeout=0.2)  # nothing listening
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        store.append(_env("x", 1))  # must not raise
    assert store.read_all() == []  # read failure returns empty, not an error
