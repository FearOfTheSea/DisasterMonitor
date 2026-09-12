"""PostgreSQL persistence for provider attempts and freshness diagnostics."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, cast

from psycopg.rows import dict_row

from disaster_monitor.domain.operations import (
    ProviderAttempt,
    ProviderAttemptOutcome,
    ProviderFreshness,
    SourceSnapshotRecord,
    freshness_for,
)
from disaster_monitor.infrastructure.operations.postgres_ingestion_evidence import (
    source_snapshot_from_row,
)
from disaster_monitor.infrastructure.operations.postgres_repository_base import (
    PostgresRepositoryBase,
)


class PostgresProviderStatusRepository(PostgresRepositoryBase):
    """Persist provider-attempt history and derive source freshness."""

    async def record_provider_attempt(self, attempt: ProviderAttempt) -> None:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO provider_attempt(
                        source_id, attempted_at, outcome, reason_code,
                        retryable, http_status, records_seen
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        attempt.source_id,
                        attempt.attempted_at,
                        attempt.outcome.value,
                        attempt.reason_code,
                        attempt.retryable,
                        attempt.http_status,
                        attempt.records_seen,
                    ),
                )

    async def provider_attempts(
        self, *, source_id: str, limit: int = 100
    ) -> tuple[ProviderAttempt, ...]:
        if not 1 <= limit <= 500:
            raise ValueError(
                "Provider attempt history limit must be between 1 and 500."
            )
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    SELECT source_id, attempted_at, outcome, reason_code,
                           retryable, http_status, records_seen
                    FROM provider_attempt
                    WHERE source_id=%s
                    ORDER BY attempted_at DESC, attempt_id DESC
                    LIMIT %s
                    """,
                    (source_id, limit),
                )
                rows = await cursor.fetchall()
        return tuple(provider_attempt_from_row(row) for row in rows)

    async def freshness(
        self,
        *,
        now: datetime,
        expectations: dict[str, timedelta],
    ) -> tuple[ProviderFreshness, ...]:
        results: list[ProviderFreshness] = []
        for source_id, expected in sorted(expectations.items()):
            snapshot = await self._latest_snapshot(source_id)
            attempts = await self.provider_attempts(source_id=source_id, limit=100)
            job = await self._latest_job(source_id)
            failed = bool(job and job["status"] in {"retry", "dead_letter"})
            last_attempt = attempts[0] if attempts else None
            consecutive = 0
            for attempt in attempts:
                if attempt.outcome not in {
                    ProviderAttemptOutcome.FAILED,
                    ProviderAttemptOutcome.INCOMPLETE,
                }:
                    break
                consecutive += 1
            if not attempts and failed:
                consecutive = 1
            results.append(
                freshness_for(
                    source_id=source_id,
                    now=now,
                    expected_freshness=expected,
                    last_attempt_at=(
                        last_attempt.attempted_at
                        if last_attempt is not None
                        else (
                            cast(datetime, job["claimed_at"] or job["created_at"])
                            if job
                            else None
                        )
                    ),
                    last_snapshot=snapshot,
                    consecutive_failures=consecutive,
                    latest_error_code=(
                        last_attempt.reason_code
                        if last_attempt is not None
                        and last_attempt.outcome
                        in {
                            ProviderAttemptOutcome.FAILED,
                            ProviderAttemptOutcome.INCOMPLETE,
                        }
                        else cast(str | None, job["last_error_code"])
                        if job
                        else None
                    ),
                )
            )
        return tuple(results)

    async def _latest_snapshot(self, source_id: str) -> SourceSnapshotRecord | None:
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    SELECT * FROM source_snapshot
                    WHERE source_id=%s
                    ORDER BY retrieved_at DESC, snapshot_id DESC
                    LIMIT 1
                    """,
                    (source_id,),
                )
                row = await cursor.fetchone()
        return None if row is None else source_snapshot_from_row(row)

    async def _latest_job(self, source_id: str) -> dict[str, Any] | None:
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    SELECT claimed_at, created_at, status, last_error_code
                    FROM ingest_job WHERE source_id=%s
                    ORDER BY COALESCE(claimed_at, created_at) DESC LIMIT 1
                    """,
                    (source_id,),
                )
                return await cursor.fetchone()


def provider_attempt_from_row(row: dict[str, Any]) -> ProviderAttempt:
    """Map one provider-attempt row at the provider-status boundary."""
    return ProviderAttempt(
        source_id=str(row["source_id"]),
        attempted_at=cast(datetime, row["attempted_at"]),
        outcome=ProviderAttemptOutcome(str(row["outcome"])),
        reason_code=(
            str(row["reason_code"]) if row["reason_code"] is not None else None
        ),
        retryable=bool(row["retryable"]),
        http_status=(
            int(row["http_status"]) if row["http_status"] is not None else None
        ),
        records_seen=int(row["records_seen"]),
    )
