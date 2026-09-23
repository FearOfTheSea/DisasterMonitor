"""Deterministic in-memory operational repository for tests and safe fallback."""

from dataclasses import replace
from datetime import datetime, timedelta

from disaster_monitor.domain.operations import (
    IngestJob,
    IngestJobStatus,
)
from disaster_monitor.infrastructure.operations.memory_state import MemoryState


class QueueMemoryPort(MemoryState):
    async def enqueue(self, job: IngestJob) -> bool:
        if job.job_id in self.jobs:
            return False
        self.jobs[job.job_id] = job
        return True

    async def claim(
        self, worker_id: str, *, now: datetime, lease_seconds: int = 300
    ) -> IngestJob | None:
        if lease_seconds < 1:
            raise ValueError("Ingest job leases must be positive.")
        for item in tuple(self.jobs.values()):
            if (
                item.status is IngestJobStatus.RUNNING
                and item.lease_expires_at is not None
                and item.lease_expires_at <= now
                and item.attempt_count >= item.max_attempts
            ):
                self.jobs[item.job_id] = replace(
                    item,
                    status=IngestJobStatus.DEAD_LETTER,
                    claimed_by=None,
                    claimed_at=None,
                    lease_expires_at=None,
                    last_error_code="lease_expired_max_attempts",
                    last_failed_at=now,
                    diagnostic="The worker lease expired after the maximum attempts.",
                )
        eligible = sorted(
            (
                item
                for item in self.jobs.values()
                if (
                    item.status in {IngestJobStatus.QUEUED, IngestJobStatus.RETRY}
                    or (
                        item.status is IngestJobStatus.RUNNING
                        and item.lease_expires_at is not None
                        and item.lease_expires_at <= now
                    )
                )
                and item.scheduled_for <= now
            ),
            key=lambda item: (item.scheduled_for, item.job_id),
        )
        if not eligible:
            return None
        job = eligible[0]
        claimed = replace(
            job,
            status=IngestJobStatus.RUNNING,
            claimed_by=worker_id,
            claimed_at=now,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            fencing_token=job.fencing_token + 1,
            attempt_count=job.attempt_count + 1,
        )
        self.jobs[job.job_id] = claimed
        return claimed

    async def renew(
        self,
        job_id: str,
        *,
        worker_id: str,
        fencing_token: int,
        now: datetime,
        lease_seconds: int = 300,
    ) -> bool:
        if lease_seconds < 1:
            raise ValueError("Ingest job leases must be positive.")
        job = self.jobs.get(job_id)
        if job is None or not _owns_claim(job, worker_id, fencing_token, now):
            return False
        self.jobs[job_id] = replace(
            job, lease_expires_at=now + timedelta(seconds=lease_seconds)
        )
        return True

    async def complete(
        self,
        job_id: str,
        *,
        completed_at: datetime,
        fencing_token: int | None = None,
    ) -> None:
        del completed_at
        job = self.jobs[job_id]
        if not _fence_matches(job, fencing_token):
            raise RuntimeError("The ingest job fencing token is no longer current.")
        self.jobs[job_id] = replace(
            job,
            status=IngestJobStatus.SUCCEEDED,
            claimed_by=None,
            claimed_at=None,
            lease_expires_at=None,
        )

    async def fail(
        self,
        job_id: str,
        *,
        failed_at: datetime,
        error_code: str,
        retry_at: datetime | None,
        fencing_token: int | None = None,
        error_detail: str | None = None,
    ) -> IngestJobStatus:
        job = self.jobs[job_id]
        if not _fence_matches(job, fencing_token):
            raise RuntimeError("The ingest job fencing token is no longer current.")
        if retry_at is None or job.attempt_count >= job.max_attempts:
            status = IngestJobStatus.DEAD_LETTER
            next_scheduled_for = job.scheduled_for
        else:
            status = IngestJobStatus.RETRY
            next_scheduled_for = retry_at
        self.jobs[job_id] = replace(
            job,
            status=status,
            scheduled_for=next_scheduled_for,
            claimed_by=None,
            claimed_at=None,
            lease_expires_at=None,
            last_error_code=error_code,
            last_failed_at=failed_at,
            diagnostic=(error_detail or "")[:2_000] or None,
        )
        return status

    async def job_status_counts(self) -> dict[IngestJobStatus, int]:
        return {
            status: sum(1 for job in self.jobs.values() if job.status == status)
            for status in IngestJobStatus
        }


def _fence_matches(job: IngestJob, fencing_token: int | None) -> bool:
    return job.status is IngestJobStatus.RUNNING and (
        fencing_token is None or job.fencing_token == fencing_token
    )


def _owns_claim(
    job: IngestJob, worker_id: str, fencing_token: int, now: datetime
) -> bool:
    return (
        _fence_matches(job, fencing_token)
        and job.claimed_by == worker_id
        and job.lease_expires_at is not None
        and job.lease_expires_at > now
    )
