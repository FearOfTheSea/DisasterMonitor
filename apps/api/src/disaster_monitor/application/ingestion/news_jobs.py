"""Duplicate-safe scheduling for configured breaking-news feeds."""

from datetime import UTC, datetime, timedelta

from disaster_monitor.application.ingestion.jobs import scheduled_job
from disaster_monitor.application.ports.ingest_jobs import IngestJobQueue


class NewsFeedScheduler:
    interval = timedelta(minutes=15)

    def __init__(self, repository: IngestJobQueue, source_ids: tuple[str, ...]) -> None:
        self._repository = repository
        self._source_ids = tuple(sorted(set(source_ids)))

    async def enqueue_due(self, *, now: datetime) -> int:
        if now.tzinfo is None:
            raise ValueError("Scheduler time must be timezone-aware.")
        seconds = int(self.interval.total_seconds())
        bucket = int(now.timestamp()) // seconds * seconds
        scheduled_for = datetime.fromtimestamp(bucket, tz=UTC)
        created = 0
        for source_id in self._source_ids:
            created += int(
                await self._repository.enqueue(
                    scheduled_job(
                        source_id=source_id,
                        request_identity=f"breaking-news:{source_id}",
                        scheduled_for=scheduled_for,
                    )
                )
            )
        return created
