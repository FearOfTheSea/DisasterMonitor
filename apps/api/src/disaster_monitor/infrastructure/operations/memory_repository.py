"""Deterministic in-memory operational repository for tests and safe fallback."""

from disaster_monitor.infrastructure.operations.memory_freshness_query import (
    MemoryFreshnessQuery,
)
from disaster_monitor.infrastructure.operations.memory_queue_port import QueueMemoryPort
from disaster_monitor.infrastructure.operations.memory_watch_port import WatchMemoryPort


class InMemoryOperationalRepository(
    QueueMemoryPort, WatchMemoryPort, MemoryFreshnessQuery
):
    """Reference implementation with the same idempotency and retry semantics."""

    durable = False
