"""Restart-safe-in-process Ground job queue for development and unit tests."""

from dataclasses import replace
from datetime import datetime, timedelta

from disaster_monitor.application.ports.ground_imagery.jobs import (
    GroundImageryJob,
    GroundImageryJobStatus,
)


class InMemoryGroundImageryJobQueue:
    durable = False

    def __init__(self) -> None:
        self.jobs: dict[str, GroundImageryJob] = {}

    async def enqueue(self, job: GroundImageryJob) -> bool:
        if job.job_id in self.jobs:
            return False
        self.jobs[job.job_id] = job
        return True

    async def claim(
        self, worker_id: str, *, now: datetime, lease_seconds: int = 300
    ) -> GroundImageryJob | None:
        if lease_seconds < 1:
            raise ValueError("Ground job leases must be positive.")
        for job_id, job in tuple(self.jobs.items()):
            if (
                job.status is GroundImageryJobStatus.RUNNING
                and job.lease_expires_at is not None
                and job.lease_expires_at <= now
                and job.attempt >= job.max_attempts
            ):
                self.jobs[job_id] = replace(
                    job,
                    status=GroundImageryJobStatus.FAILED,
                    claimed_by=None,
                    claimed_at=None,
                    lease_expires_at=None,
                    error_code="lease_expired",
                    diagnostic=(
                        "The maximum Ground job attempts were exhausted after "
                        "lease expiry."
                    ),
                    updated_at=now,
                )
        eligible = sorted(
            (
                job
                for job in self.jobs.values()
                if (
                    job.status
                    in {
                        GroundImageryJobStatus.QUEUED,
                        GroundImageryJobStatus.RETRY_WAIT,
                    }
                    or (
                        job.status is GroundImageryJobStatus.RUNNING
                        and job.lease_expires_at is not None
                        and job.lease_expires_at <= now
                        and job.attempt < job.max_attempts
                    )
                )
                and job.next_attempt_at <= now
                and not any(
                    active.job_id != job.job_id
                    and active.request_id == job.request_id
                    and active.status is GroundImageryJobStatus.RUNNING
                    and active.lease_expires_at is not None
                    and active.lease_expires_at > now
                    for active in self.jobs.values()
                )
            ),
            key=lambda job: (job.next_attempt_at, job.job_id),
        )
        if not eligible:
            return None
        job = eligible[0]
        claimed = replace(
            job,
            status=GroundImageryJobStatus.RUNNING,
            attempt=job.attempt + 1,
            claimed_by=worker_id,
            claimed_at=now,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            fencing_token=job.fencing_token + 1,
            updated_at=now,
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
        job = self.jobs.get(job_id)
        if (
            job is None
            or job.status is not GroundImageryJobStatus.RUNNING
            or job.claimed_by != worker_id
            or job.fencing_token != fencing_token
            or job.lease_expires_at is None
            or job.lease_expires_at <= now
        ):
            return False
        self.jobs[job_id] = replace(
            job,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            updated_at=now,
        )
        return True

    async def complete(
        self, job_id: str, *, completed_at: datetime, fencing_token: int
    ) -> None:
        job = self._current(job_id, fencing_token)
        self.jobs[job_id] = replace(
            job,
            status=GroundImageryJobStatus.SUCCEEDED,
            claimed_by=None,
            claimed_at=None,
            lease_expires_at=None,
            updated_at=completed_at,
        )

    async def fail(
        self,
        job_id: str,
        *,
        failed_at: datetime,
        fencing_token: int,
        error_code: str,
        error_detail: str,
        retry_at: datetime | None,
    ) -> GroundImageryJob:
        job = self._current(job_id, fencing_token)
        retryable = retry_at is not None and job.attempt < job.max_attempts
        updated = replace(
            job,
            status=(
                GroundImageryJobStatus.RETRY_WAIT
                if retryable
                else GroundImageryJobStatus.FAILED
            ),
            next_attempt_at=retry_at or failed_at,
            claimed_by=None,
            claimed_at=None,
            lease_expires_at=None,
            error_code=error_code,
            diagnostic=error_detail[:2_000],
            updated_at=failed_at,
        )
        self.jobs[job_id] = updated
        return updated

    async def jobs_for_request(self, request_id: str) -> tuple[GroundImageryJob, ...]:
        return tuple(
            sorted(
                (job for job in self.jobs.values() if job.request_id == request_id),
                key=lambda job: (job.created_at, job.job_id),
                reverse=True,
            )
        )

    def _current(self, job_id: str, fencing_token: int) -> GroundImageryJob:
        job = self.jobs.get(job_id)
        if (
            job is None
            or job.status is not GroundImageryJobStatus.RUNNING
            or job.fencing_token != fencing_token
        ):
            raise RuntimeError("The Ground job fencing token is no longer current.")
        return job
