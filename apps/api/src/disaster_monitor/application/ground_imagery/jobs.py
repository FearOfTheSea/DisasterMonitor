"""Versioned, leased Ground preparation jobs and bounded retry policy."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from disaster_monitor.application.ports.ground_imagery.jobs import (
    GroundImageryJob,
    GroundImageryJobQueue,
    GroundImageryJobStatus,
)
from disaster_monitor.application.ports.provider_budget import (
    ProviderBudgetExceeded,
    ProviderBudgetLedger,
)


def retry_time(*, failed_at: datetime, attempt: int) -> datetime:
    """Return bounded exponential backoff without unbounded worker sleeps."""
    return failed_at + timedelta(seconds=min(3_600, 30 * (2 ** max(0, attempt - 1))))


class GroundPreparationExecutor(Protocol):
    async def execute_preparation_job(self, job: GroundImageryJob) -> object: ...

    async def mark_preparation_failed(
        self, request_id: str, *, detail: str
    ) -> object: ...


class GroundImageryLeaseLost(RuntimeError):
    """The worker no longer owns the right to publish Ground job state."""


class GroundImageryWorker:
    """Execute leased Ground preparation jobs with bounded provider usage."""

    def __init__(
        self,
        queue: GroundImageryJobQueue,
        executor: GroundPreparationExecutor,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        budget_ledger: ProviderBudgetLedger | None = None,
        budget_limit_units: int = 100,
        lease_seconds: int = 300,
        provider_id: str = "copernicus-data-space-ground",
    ) -> None:
        if budget_limit_units < 1 or lease_seconds < 1:
            raise ValueError("Ground worker limits must be positive.")
        self._queue = queue
        self._executor = executor
        self._clock = clock
        self._budget_ledger = budget_ledger
        self._budget_limit_units = budget_limit_units
        self._lease_seconds = lease_seconds
        self._provider_id = provider_id

    async def run_once(self, worker_id: str) -> GroundImageryJob | None:
        now = self._clock()
        job = await self._queue.claim(
            worker_id, now=now, lease_seconds=self._lease_seconds
        )
        if job is None:
            return None
        reservation_id: str | None = None
        budget_ledger = self._budget_ledger
        try:
            if budget_ledger is not None:
                reservation = await budget_ledger.reserve(
                    self._provider_id,
                    worker_id=worker_id,
                    estimated_units=1,
                    limit_units=self._budget_limit_units,
                    now=now,
                )
                reservation_id = reservation.reservation_id
            await self._execute_with_lease(job, worker_id)
            if reservation_id is not None and budget_ledger is not None:
                await budget_ledger.settle(
                    reservation_id, actual_units=1, now=self._clock()
                )
            await self._queue.complete(
                job.job_id,
                completed_at=self._clock(),
                fencing_token=job.fencing_token,
            )
        except Exception as error:
            if reservation_id is not None and budget_ledger is not None:
                await budget_ledger.release(reservation_id, now=self._clock())
            failed_at = self._clock()
            retry_at = (
                retry_time(failed_at=failed_at, attempt=job.attempt)
                if job.attempt < job.max_attempts
                else None
            )
            error_code = (
                "provider_budget_exceeded"
                if isinstance(error, ProviderBudgetExceeded)
                else "ground_preparation_failed"
            )
            try:
                failed = await self._queue.fail(
                    job.job_id,
                    failed_at=failed_at,
                    fencing_token=job.fencing_token,
                    error_code=error_code,
                    error_detail=str(error),
                    retry_at=retry_at,
                )
            except RuntimeError:
                # A lease may have been fenced while the provider call was in
                # flight. The newer worker owns the terminal transition.
                return job
            if failed.status is GroundImageryJobStatus.FAILED:
                await self._executor.mark_preparation_failed(
                    job.request_id, detail=str(error)
                )
        return job

    async def _execute_with_lease(self, job: GroundImageryJob, worker_id: str) -> None:
        execution = asyncio.create_task(self._executor.execute_preparation_job(job))
        renewal = asyncio.create_task(self._renew_lease(job, worker_id))
        try:
            done, _ = await asyncio.wait(
                {execution, renewal}, return_when=asyncio.FIRST_COMPLETED
            )
            if renewal in done:
                await renewal
            await execution
        finally:
            for task in (execution, renewal):
                if not task.done():
                    task.cancel()
            await asyncio.gather(execution, renewal, return_exceptions=True)

    async def _renew_lease(self, job: GroundImageryJob, worker_id: str) -> None:
        interval = max(0.1, min(30.0, self._lease_seconds / 3))
        while True:
            await asyncio.sleep(interval)
            renewed = await self._queue.renew(
                job.job_id,
                worker_id=worker_id,
                fencing_token=job.fencing_token,
                now=self._clock(),
                lease_seconds=self._lease_seconds,
            )
            if not renewed:
                raise GroundImageryLeaseLost(
                    "The Ground job lease expired or was fenced by another worker."
                )
