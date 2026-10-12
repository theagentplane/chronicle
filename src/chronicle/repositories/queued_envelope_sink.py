"""``QueuedEnvelopeSink``: non-blocking enqueue with background, batched delivery (design 5.1).

``write_*`` places the record on an in-memory queue and returns. A background thread sends spans
one at a time and envelopes in batches, always in enqueue order, so a span's open write reaches
the control plane before its envelopes. ``flush`` is called at span end and at shutdown; it waits
until what was enqueued has been delivered or has failed.

Failure policy (``DeliveryPolicy``): with ``fail_open`` the failure is logged and the records are
dropped, so recording never breaks the agent. In strict mode the failure is kept and ``flush``
raises ``DeliveryError``, which fails the request at span end. Batching is an internal detail of
this class, not part of the contract. Because there is no local buffer on disk, a crash can lose
queued items.
"""

import atexit
import logging
import queue
import threading
from collections.abc import Callable
from functools import partial
from typing import Any

from agentplane_primitives.models import Envelope, Span

from chronicle.repositories.delivery_enums import OverflowPolicy
from chronicle.repositories.delivery_types import DeliveryPolicy
from chronicle.repositories.errors import ControlPlaneError, DeliveryError
from chronicle.repositories.repository_types import ControlPlaneClient

_log = logging.getLogger("chronicle.delivery")


class _Flush:
    """A marker in the queue: everything before it must be delivered, then ``done`` is set."""

    def __init__(self) -> None:
        self.done = threading.Event()


class QueuedEnvelopeSink:
    """Implements ``EnvelopeSink`` on top of a ``ControlPlaneClient``."""

    def __init__(self, client: ControlPlaneClient, policy: DeliveryPolicy | None = None) -> None:
        self._client = client
        self._policy = policy or DeliveryPolicy()
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=self._policy.max_queue)
        self._errors: list[ControlPlaneError] = []
        self._errors_lock = threading.Lock()
        self._dropped = 0
        self._thread: threading.Thread | None = None
        self._thread_lock = threading.Lock()
        self._closed = False
        atexit.register(self.flush_quietly)

    # ---- EnvelopeSink --------------------------------------------------------------------

    def write_span(self, span: Span) -> None:
        self._enqueue(span)

    def write_envelope(self, envelope: Envelope) -> None:
        self._enqueue(envelope)

    def flush(self) -> None:
        """Deliver everything enqueued so far; raise ``DeliveryError`` in strict mode."""
        if self._thread is not None and self._thread.is_alive():
            marker = _Flush()
            self._queue.put(marker)
            marker.done.wait(timeout=max(self._policy.timeout * 4, 30.0))
        with self._errors_lock:
            errors, self._errors = self._errors, []
        if errors and not self._policy.fail_open:
            raise DeliveryError(f"{len(errors)} write(s) failed: {errors[0]}")

    def close(self, *, close_client: bool = True) -> None:
        """Flush and stop the background thread; also close the client unless told not to."""
        self.flush_quietly()
        self._closed = True
        if self._thread is not None:
            self._queue.put(None)
            self._thread.join(timeout=5)
        if close_client:
            self._client.close()

    @property
    def dropped(self) -> int:
        """How many records were dropped because the queue was full."""
        return self._dropped

    # ---- internals -----------------------------------------------------------------------

    def _enqueue(self, item: Span | Envelope) -> None:
        self._ensure_thread()
        try:
            if self._policy.on_overflow is OverflowPolicy.BLOCK:
                self._queue.put(item, timeout=self._policy.timeout)
            else:
                self._queue.put_nowait(item)
        except queue.Full:
            self._dropped += 1
            _log.warning("chronicle delivery queue is full; dropped a record")

    def _ensure_thread(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        with self._thread_lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run, name="chronicle-delivery", daemon=True
                )
                self._thread.start()

    def flush_quietly(self) -> None:
        """Flush, logging instead of raising (used at exit and when the sink is replaced)."""
        try:
            self.flush()
        except Exception:
            _log.warning("chronicle could not flush at exit", exc_info=True)

    def _run(self) -> None:
        pending: list[Envelope] = []
        while True:
            try:
                item = self._queue.get(timeout=self._policy.flush_interval)
            except queue.Empty:
                self._send_batch(pending)
                continue
            if item is None:
                self._send_batch(pending)
                return
            if isinstance(item, _Flush):
                self._send_batch(pending)
                item.done.set()
            elif isinstance(item, Span):
                self._send_batch(pending)  # keep enqueue order across kinds
                self._guarded(partial(self._client.upsert_span, item))
            else:
                pending.append(item)
                if len(pending) >= self._policy.batch_size:
                    self._send_batch(pending)

    def _send_batch(self, pending: list[Envelope]) -> None:
        if not pending:
            return
        batch = list(pending)
        pending.clear()
        self._guarded(partial(self._client.append_envelopes, batch))

    def _guarded(self, action: Callable[[], None]) -> None:
        try:
            action()
        except ControlPlaneError as exc:
            self._record_error(exc)
        except Exception as exc:  # never let the delivery thread die
            self._record_error(ControlPlaneError(f"unexpected delivery error: {exc}"))

    def _record_error(self, exc: ControlPlaneError) -> None:
        _log.warning("chronicle delivery failed: %s", exc)
        with self._errors_lock:
            self._errors.append(exc)
