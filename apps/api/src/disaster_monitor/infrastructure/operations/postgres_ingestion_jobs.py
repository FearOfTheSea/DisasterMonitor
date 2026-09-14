"""PostgreSQL persistence for the durable ingestion queue."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, cast

from psycopg.rows import dict_row

from disaster_monitor.domain.operations import (
    IngestJob,
    IngestJobStatus,
)
from disaster_monitor.infrastructure.operations.postgres_repository_base import (
    PostgresRepositoryBase,
)


class PostgresIngestionJobRepository(PostgresRepositoryBase):
    """Transactional queue lifecycle with SKIP LOCKED claims."""

    async def enqueue(self, job: IngestJob) -> bool:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO source(source_id) VALUES (%s)
                    ON CONFLICT (source_id) DO NOTHING
                    """,
                    (job.source_id,),
                )
                await cursor.execute(
                    """
                    INSERT INTO ingest_job(
                        job_id, source_id, canonical_request_identity,
                        scheduled_for, status, attempt_count, max_attempts, created_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (job_id) DO NOTHING
                    """,
                    (
                        job.job_id,
                        job.source_id,
                        job.canonical_request_identity,
                        job.scheduled_for,
                        job.status.value,
                        job.attempt_count,
                        job.max_attempts,
                        job.created_at,
                    ),
                )
                return cursor.rowcount == 1

    async def claim(
        self, worker_id: str, *, now: datetime, lease_seconds: int = 300
    ) -> IngestJob | None:
        if lease_seconds < 1:
            raise ValueError("Ingest job leases must be positive.")
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    UPDATE ingest_job
                    SET status='dead_letter',
                        last_error_code='lease_expired_max_attempts',
                        last_failed_at=%s,
                        diagnostic=(
                            'The worker lease expired after the maximum attempts.'
                        ),
                        claimed_by=NULL, claimed_at=NULL, lease_expires_at=NULL
                    WHERE status='running' AND lease_expires_at <= %s
                      AND attempt_count >= max_attempts
                    """,
                    (now, now),
                )
                await cursor.execute(
                    """
                    WITH candidate AS (
                        SELECT job_id FROM ingest_job
                        WHERE (
                            status IN ('queued', 'retry')
                            OR (status='running' AND lease_expires_at <= %s
                                AND attempt_count < max_attempts)
                        ) AND scheduled_for <= %s
                        ORDER BY scheduled_for, job_id
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE ingest_job AS job
                    SET status='running', claimed_by=%s, claimed_at=%s,
                        lease_expires_at=%s, fencing_token=fencing_token+1,
                        attempt_count=attempt_count+1
                    FROM candidate
                    WHERE job.job_id=candidate.job_id
                    RETURNING job.*
                    """,
                    (now, now, worker_id, now, now + timedelta(seconds=lease_seconds)),
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
        if lease_seconds < 1:
            raise ValueError("Ingest job leases must be positive.")
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE ingest_job
                    SET lease_expires_at=%s
                    WHERE job_id=%s AND status='running' AND claimed_by=%s
                      AND fencing_token=%s AND lease_expires_at > %s
                    """,
                    (
                        now + timedelta(seconds=lease_seconds),
                        job_id,
                        worker_id,
                        fencing_token,
                        now,
                    ),
                )
                return cursor.rowcount == 1

    async def complete(
        self,
        job_id: str,
        *,
        completed_at: datetime,
        fencing_token: int | None = None,
    ) -> None:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE ingest_job SET status='succeeded', completed_at=%s,
                        claimed_by=NULL, claimed_at=NULL, lease_expires_at=NULL
                    WHERE job_id=%s AND status='running'
                      AND (%s::bigint IS NULL OR fencing_token=%s::bigint)
                    """,
                    (completed_at, job_id, fencing_token, fencing_token),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError(
                        "Only the current fenced ingest worker can complete the job."
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
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                if retry_at is None:
                    await cursor.execute(
                        """
                        UPDATE ingest_job
                        SET status='dead_letter', last_error_code=%s,
                            last_failed_at=%s, diagnostic=%s,
                            claimed_by=NULL, claimed_at=NULL, lease_expires_at=NULL
                        WHERE job_id=%s AND status='running'
                          AND (%s::bigint IS NULL OR fencing_token=%s::bigint)
                        RETURNING status
                        """,
                        (
                            error_code,
                            failed_at,
                            (error_detail or "")[:2_000] or None,
                            job_id,
                            fencing_token,
                            fencing_token,
                        ),
                    )
                else:
                    await cursor.execute(
                        """
                        UPDATE ingest_job
                        SET status=CASE WHEN attempt_count >= max_attempts
                                        THEN 'dead_letter' ELSE 'retry' END,
                            scheduled_for=CASE WHEN attempt_count >= max_attempts
                                               THEN scheduled_for ELSE %s END,
                            last_error_code=%s, last_failed_at=%s, diagnostic=%s,
                            claimed_by=NULL, claimed_at=NULL, lease_expires_at=NULL
                        WHERE job_id=%s AND status='running'
                          AND (%s::bigint IS NULL OR fencing_token=%s::bigint)
                        RETURNING status
                        """,
                        (
                            retry_at,
                            error_code,
                            failed_at,
                            (error_detail or "")[:2_000] or None,
                            job_id,
                            fencing_token,
                            fencing_token,
                        ),
                    )
                row = await cursor.fetchone()
                if row is None:
                    raise RuntimeError("Only a running ingest job can fail.")
                return IngestJobStatus(str(row["status"]))

    async def job_status_counts(self) -> dict[IngestJobStatus, int]:
        counts = {status: 0 for status in IngestJobStatus}
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    "SELECT status, COUNT(*) AS count FROM ingest_job GROUP BY status"
                )
                rows = await cursor.fetchall()
        for row in rows:
            counts[IngestJobStatus(str(row["status"]))] = int(row["count"])
        return counts


def _job(row: dict[str, Any]) -> IngestJob:
    return IngestJob(
        job_id=str(row["job_id"]),
        source_id=str(row["source_id"]),
        canonical_request_identity=str(row["canonical_request_identity"]),
        scheduled_for=cast(datetime, row["scheduled_for"]),
        status=IngestJobStatus(str(row["status"])),
        attempt_count=int(row["attempt_count"]),
        max_attempts=int(row["max_attempts"]),
        created_at=cast(datetime, row["created_at"]),
        claimed_by=cast(str | None, row["claimed_by"]),
        claimed_at=cast(datetime | None, row["claimed_at"]),
        last_error_code=cast(str | None, row["last_error_code"]),
        lease_expires_at=cast(datetime | None, row.get("lease_expires_at")),
        fencing_token=int(row.get("fencing_token", 0)),
        last_failed_at=cast(datetime | None, row.get("last_failed_at")),
        diagnostic=cast(str | None, row.get("diagnostic")),
    )
