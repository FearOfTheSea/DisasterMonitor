"""Contracts and persistence port for background Ground artifact preparation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from disaster_monitor.domain.imagery.observations import Sensor, TemporalRole


class GroundImageryJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class GroundImageryJob:
    job_id: str
    request_id: str
    request_version: int
    sensor: Sensor
    role: TemporalRole
    overview: bool
    output_kind: str | None
    status: GroundImageryJobStatus
    attempt: int
    max_attempts: int
    next_attempt_at: datetime
    created_at: datetime
    updated_at: datetime
    claimed_by: str | None = None
    claimed_at: datetime | None = None
    lease_expires_at: datetime | None = None
    fencing_token: int = 0
    error_code: str | None = None
    diagnostic: str | None = None

    def __post_init__(self) -> None:
        if not self.job_id.strip() or not self.request_id.strip():
            raise ValueError("Ground jobs require stable request identity.")
        if self.request_version < 1 or self.attempt < 0 or self.max_attempts < 1:
            raise ValueError("Ground job version or attempt bounds are invalid.")
        if self.fencing_token < 0:
            raise ValueError("Ground job fencing tokens cannot be negative.")
        for value in (
            self.next_attempt_at,
            self.created_at,
            self.updated_at,
            self.claimed_at,
            self.lease_expires_at,
        ):
            if value is not None and value.tzinfo is None:
                raise ValueError("Ground job timestamps must be timezone-aware.")


def preparation_job(
    *,
    request_id: str,
    request_version: int,
    sensor: Sensor,
    role: TemporalRole,
    overview: bool,
    output_kind: str | None,
    now: datetime,
    max_attempts: int = 4,
) -> GroundImageryJob:
    material = "|".join(
        (
            request_id,
            str(request_version),
            sensor.value,
            role.value,
            str(overview),
            output_kind or "",
        )
    )
    digest = hashlib.sha256(material.encode()).hexdigest()[:24]
    return GroundImageryJob(
        job_id=f"ground-job:{digest}",
        request_id=request_id,
        request_version=request_version,
        sensor=sensor,
        role=role,
        overview=overview,
        output_kind=output_kind,
        status=GroundImageryJobStatus.QUEUED,
        attempt=0,
        max_attempts=max_attempts,
        next_attempt_at=now,
        created_at=now,
        updated_at=now,
    )


class GroundImageryJobQueue(Protocol):
    async def enqueue(self, job: GroundImageryJob) -> bool: ...

    async def claim(
        self, worker_id: str, *, now: datetime, lease_seconds: int = 300
    ) -> GroundImageryJob | None: ...

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
        self, job_id: str, *, completed_at: datetime, fencing_token: int
    ) -> None: ...

    async def fail(
        self,
        job_id: str,
        *,
        failed_at: datetime,
        fencing_token: int,
        error_code: str,
        error_detail: str,
        retry_at: datetime | None,
    ) -> GroundImageryJob: ...

    async def jobs_for_request(
        self, request_id: str
    ) -> tuple[GroundImageryJob, ...]: ...
