"""Durable scheduling for the worldwide incident projection refresh."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

from disaster_monitor.application.ingestion.jobs import scheduled_job
from disaster_monitor.application.ports.ingest_jobs import IngestJobQueue


class IncidentProjectionRefresher(Protocol):
    async def refresh(self) -> object: ...


class WorldwideIncidentProjectionScheduler:
    """Create one duplicate-safe worldwide refresh job per interval bucket."""

    source_id = "worldwide-incident-projection"
    interval = timedelta(minutes=5)

    def __init__(self, repository: IngestJobQueue) -> None:
        self._repository = repository

    async def enqueue_due(self, *, now: datetime) -> int:
        if now.tzinfo is None:
            raise ValueError("Scheduler time must be timezone-aware.")
        seconds = int(self.interval.total_seconds())
        bucket = int(now.timestamp()) // seconds * seconds
        scheduled_for = datetime.fromtimestamp(bucket, tz=UTC)
        job = scheduled_job(
            source_id=self.source_id,
            request_identity=self.source_id,
            scheduled_for=scheduled_for,
        )
        return int(await self._repository.enqueue(job))
