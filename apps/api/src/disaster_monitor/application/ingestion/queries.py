"""Operational queue status available to transport-independent monitoring."""

from disaster_monitor.application.ports.ingest_jobs import JobStatusReader
from disaster_monitor.domain.operations import IngestJobStatus


class QueueStatusQuery:
    def __init__(self, reader: JobStatusReader) -> None:
        self._reader = reader

    async def execute(self) -> dict[IngestJobStatus, int]:
        return await self._reader.job_status_counts()
