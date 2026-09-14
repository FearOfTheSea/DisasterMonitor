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

    async def claim(
        self,
        worker_id: str,
        *,
        now: datetime,
        lease_seconds: int = 300,
    ) -> IngestJob | None: ...

    async def renew(
        self,
        job_id: str,
        *,
        worker_id: str,
        fencing_token: int,
        now: datetime,
        lease_seconds: int = 300,
    ) -> bool: ...

    async def complete(
        self,
        job_id: str,
        *,
        completed_at: datetime,
        fencing_token: int | None = None,
    ) -> None: ...

    async def fail(
        self,
        job_id: str,
        *,
        failed_at: datetime,
        error_code: str,
        retry_at: datetime | None,
        fencing_token: int | None = None,
        error_detail: str | None = None,
    ) -> IngestJobStatus: ...


class JobStatusReader(Protocol):
    async def job_status_counts(self) -> dict[IngestJobStatus, int]: ...
