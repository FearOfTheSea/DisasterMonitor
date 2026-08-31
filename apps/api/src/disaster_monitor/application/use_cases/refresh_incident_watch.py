"""Refresh one watch through provider-backed discovery and deterministic changes."""

from dataclasses import dataclass
from typing import Protocol

from disaster_monitor.application.ports.incident_watch_store import IncidentWatchStore
from disaster_monitor.application.services.incident_change_detection import (
    IncidentChangeDetector,
)
from disaster_monitor.domain.disaster import (
    IncidentWatch,
    IncidentWatchChange,
    IncidentWatchObservation,
)


class IncidentWatchDiscovery(Protocol):
    async def observe_watch(self, watch: IncidentWatch) -> IncidentWatchObservation: ...


class IncidentWatchRefreshRetryableError(RuntimeError):
    pass


class IncidentWatchRefreshNotFoundError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class IncidentWatchRefreshResult:
    watch: IncidentWatch
    observation: IncidentWatchObservation | None
    changes: tuple[IncidentWatchChange, ...]


class RefreshIncidentWatch:
    def __init__(
        self,
        store: IncidentWatchStore,
        discovery: IncidentWatchDiscovery,
        detector: IncidentChangeDetector | None = None,
    ) -> None:
        self._store = store
        self._discovery = discovery
        self._detector = detector or IncidentChangeDetector()

    async def execute(self, watch_id: str) -> IncidentWatchRefreshResult:
        watch = await self._store.get_watch(watch_id)
        if watch is None:
            raise IncidentWatchRefreshNotFoundError(watch_id)
        if not watch.enabled:
            return IncidentWatchRefreshResult(watch, None, ())
        previous = await self._store.latest_watch_observation(watch_id)
        previous_successful = await self._store.latest_successful_watch_observation(
            watch_id
        )
        current = await self._discovery.observe_watch(watch)
        if current.watch_id != watch_id:
            raise ValueError("Watch discovery returned state for a different watch.")
        changes = self._detector.detect(
            watch=watch,
            previous=previous,
            previous_successful=previous_successful,
            current=current,
        )
        await self._store.record_watch_refresh(current, changes)
        updated = await self._store.get_watch(watch_id)
        if updated is None:
            raise IncidentWatchRefreshNotFoundError(watch_id)
        if current.retryable:
            raise IncidentWatchRefreshRetryableError(
                "Incident watch provider retrieval should be retried."
            )
        return IncidentWatchRefreshResult(updated, current, changes)
