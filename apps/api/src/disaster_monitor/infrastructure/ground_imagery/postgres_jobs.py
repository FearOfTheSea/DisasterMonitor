"""PostgreSQL lease/fencing queue for Ground imagery preparation."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, cast

from psycopg.rows import dict_row

from disaster_monitor.application.ports.ground_imagery.jobs import (
    GroundImageryJob,
    GroundImageryJobQueue,
    GroundImageryJobStatus,
)
from disaster_monitor.domain.imagery.observations import Sensor, TemporalRole
from disaster_monitor.infrastructure.operations.postgres_repository_base import (
    PostgresRepositoryBase,
)


class PostgresGroundImageryJobQueue(PostgresRepositoryBase, GroundImageryJobQueue):
    durable = True

    def __init__(self, dsn: str) -> None:
        if not dsn.strip():
            raise ValueError("PostgreSQL DSN must not be empty.")
        self._dsn = dsn

    async def enqueue(self, job: GroundImageryJob) -> bool:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO imagery_jobs(
                        job_id, request_id, request_version, stage, status, attempt,
                        max_attempts, next_attempt_at, progress, error_code,
                        diagnostic, created_at, updated_at
                    ) VALUES (%s,%s,%s,'prepare',%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)
                    ON CONFLICT (job_id) DO NOTHING
                    """,
                    (
                        job.job_id,
                        job.request_id,
                        job.request_version,
                        job.status.value,
                        job.attempt,
                        job.max_attempts,
                        job.next_attempt_at,
                        _progress(job),
                        job.error_code,
                        job.diagnostic,
                        job.created_at,
                        job.updated_at,
                    ),
                )
                return cursor.rowcount == 1

    async def claim(
        self, worker_id: str, *, now: datetime, lease_seconds: int = 300
    ) -> GroundImageryJob | None:
        if lease_seconds < 1:
            raise ValueError("Ground job leases must be positive.")
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    UPDATE imagery_jobs
                    SET status='failed', error_code='lease_expired',
                        diagnostic=(
                            'The maximum Ground job attempts were exhausted '
                            'after lease expiry.'
                        ),
                        progress=jsonb_build_object(
                            'diagnostic',
                            (
                                'The maximum Ground job attempts were exhausted '
                                'after lease expiry.'
                            )
                        ),
                        claimed_by=NULL, claimed_at=NULL, lease_expires_at=NULL,
                        updated_at=%s
                    WHERE status='running' AND lease_expires_at <= %s
                      AND attempt >= max_attempts
                    """,
                    (now, now),
                )
                await cursor.execute(
                    """
                    WITH candidate AS (
                        SELECT pending.job_id FROM imagery_jobs AS pending
                        JOIN imagery_requests AS request
                          ON request.request_id=pending.request_id
                        WHERE (
                            pending.status IN ('queued','retry_wait')
                            OR (pending.status='running'
                                AND pending.lease_expires_at <= %s
                                AND pending.attempt < pending.max_attempts)
                        ) AND pending.next_attempt_at <= %s
                          AND NOT EXISTS (
                            SELECT 1 FROM imagery_jobs AS active
                            WHERE active.request_id=pending.request_id
                              AND active.job_id<>pending.job_id
                              AND active.status='running'
                              AND active.lease_expires_at > %s
                          )
                        ORDER BY pending.next_attempt_at, pending.job_id
                        FOR UPDATE OF pending, request SKIP LOCKED LIMIT 1
                    )
                    UPDATE imagery_jobs AS job
                    SET status='running', attempt=attempt+1, claimed_by=%s,
                        claimed_at=%s, lease_expires_at=%s,
                        fencing_token=fencing_token+1, updated_at=%s
                    FROM candidate WHERE job.job_id=candidate.job_id
                    RETURNING job.*
                    """,
                    (
                        now,
                        now,
                        now,
                        worker_id,
                        now,
                        now + timedelta(seconds=lease_seconds),
                        now,
                    ),
                )
                row = await cursor.fetchone()
        return None if row is None else _job(row)

    async def renew(
        self,
        job_id: str,
        *,
        worker_id: str,
        fencing_token: int,
        now: datetime,
        lease_seconds: int = 300,
    ) -> bool:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE imagery_jobs SET lease_expires_at=%s, updated_at=%s
                    WHERE job_id=%s AND status='running' AND claimed_by=%s
                      AND fencing_token=%s AND lease_expires_at > %s
                    """,
                    (
                        now + timedelta(seconds=lease_seconds),
                        now,
                        job_id,
                        worker_id,
                        fencing_token,
                        now,
                    ),
                )
                return cursor.rowcount == 1

    async def complete(
        self, job_id: str, *, completed_at: datetime, fencing_token: int
    ) -> None:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE imagery_jobs
                    SET status='succeeded', claimed_by=NULL, claimed_at=NULL,
                        lease_expires_at=NULL, updated_at=%s
                    WHERE job_id=%s AND status='running' AND fencing_token=%s
                    """,
                    (completed_at, job_id, fencing_token),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError(
                        "The Ground job fencing token is no longer current."
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
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    UPDATE imagery_jobs
                    SET status=CASE WHEN %s::timestamptz IS NOT NULL
                                         AND attempt < max_attempts
                                    THEN 'retry_wait' ELSE 'failed' END,
                        next_attempt_at=COALESCE(%s::timestamptz, %s), error_code=%s,
                        diagnostic=%s,
                        progress=jsonb_build_object('diagnostic', %s::text),
                        claimed_by=NULL, claimed_at=NULL, lease_expires_at=NULL,
                        updated_at=%s
                    WHERE job_id=%s AND status='running' AND fencing_token=%s
                    RETURNING *
                    """,
                    (
                        retry_at,
                        retry_at,
                        failed_at,
                        error_code,
                        error_detail[:2_000],
                        error_detail[:2_000],
                        failed_at,
                        job_id,
                        fencing_token,
                    ),
                )
                row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("The Ground job fencing token is no longer current.")
        return _job(row)

    async def jobs_for_request(self, request_id: str) -> tuple[GroundImageryJob, ...]:
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    SELECT * FROM imagery_jobs WHERE request_id=%s
                    ORDER BY created_at DESC, job_id DESC
                    """,
                    (request_id,),
                )
                rows = await cursor.fetchall()
        return tuple(_job(row) for row in rows)


def _progress(job: GroundImageryJob) -> str:
    return json.dumps(
        {
            "sensor": job.sensor.value,
            "role": job.role.value,
            "overview": job.overview,
            "output_kind": job.output_kind,
        },
        separators=(",", ":"),
    )


def _job(row: dict[str, Any]) -> GroundImageryJob:
    progress = row.get("progress") or {}
    if isinstance(progress, str):
        progress = json.loads(progress)
    return GroundImageryJob(
        job_id=str(row["job_id"]),
        request_id=str(row["request_id"]),
        request_version=int(row["request_version"]),
        sensor=Sensor(str(progress.get("sensor", "sentinel-1"))),
        role=TemporalRole(str(progress.get("role", "latest_useful"))),
        overview=bool(progress.get("overview", True)),
        output_kind=(
            str(progress["output_kind"]) if progress.get("output_kind") else None
        ),
        status=GroundImageryJobStatus(str(row["status"])),
        attempt=int(row["attempt"]),
        max_attempts=int(row.get("max_attempts", 4)),
        next_attempt_at=cast(datetime, row["next_attempt_at"]),
        created_at=cast(datetime, row["created_at"]),
        updated_at=cast(datetime, row["updated_at"]),
        claimed_by=cast(str | None, row.get("claimed_by")),
        claimed_at=cast(datetime | None, row.get("claimed_at")),
        lease_expires_at=cast(datetime | None, row.get("lease_expires_at")),
        fencing_token=int(row.get("fencing_token", 0)),
        error_code=cast(str | None, row.get("error_code")),
        diagnostic=(
            str(row.get("diagnostic"))
            if row.get("diagnostic")
            else (
                str(progress.get("diagnostic")) if progress.get("diagnostic") else None
            )
        ),
    )
