"""``DeliveryPolicy``: how queued writes reach the control plane (design section 5.1).

Delivery policy is explicit configuration: queue size, overflow behaviour (drop or block),
timeout, and fail-open versus strict. Because there is no local buffer on disk, a crash can lose
queued items.
"""

from dataclasses import dataclass

from chronicle.repositories.delivery_enums import OverflowPolicy


@dataclass(frozen=True)
class DeliveryPolicy:
    """Buffering and failure behaviour of the writer."""

    batch_size: int = 50
    flush_interval: float = 1.0
    max_queue: int = 10_000
    on_overflow: OverflowPolicy = OverflowPolicy.DROP
    timeout: float = 5.0
    fail_open: bool = True
