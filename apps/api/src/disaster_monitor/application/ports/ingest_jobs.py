"""Ports for durable evidence snapshots, jobs, history, and attribution."""

from datetime import datetime
from typing import Protocol

from disaster_monitor.domain.operations import (
    IngestJob,
    IngestJobStatus,
)


class IngestJobQueue(Protocol):
    """Queue lifecycle; a missing retry time means terminal failure."""

    async def enqueue(self, job: IngestJob) -> bool: ...

    async def claim(self, worker_id: str, *, now: datetime) -> IngestJob | None: ...

    async def complete(self, job_id: str, *, completed_at: datetime) -> None: ...

    async def fail(
        self,
        job_id: str,
        *,
        failed_at: datetime,
        error_code: str,
        retry_at: datetime | None,
    ) -> IngestJobStatus: ...


class JobStatusReader(Protocol):
    async def job_status_counts(self) -> dict[IngestJobStatus, int]: ...
