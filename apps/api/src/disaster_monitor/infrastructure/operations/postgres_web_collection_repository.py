"""PostgreSQL state and immutable audits for controlled web collection."""

from datetime import datetime
from typing import Any, cast

from psycopg.rows import dict_row

from disaster_monitor.domain.web_collection import (
    WebFetchAudit,
    WebFetchOutcome,
    WebFetchState,
)
from disaster_monitor.infrastructure.operations.postgres_repository_base import (
    PostgresRepositoryBase,
)


class PostgresWebCollectionRepository(PostgresRepositoryBase):
    async def read_web_fetch_state(self, source_id: str) -> WebFetchState | None:
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    "SELECT * FROM web_fetch_state WHERE source_id = %s", (source_id,)
                )
                row = await cursor.fetchone()
        return None if row is None else _state(row)

    async def save_web_fetch_state(self, state: WebFetchState) -> None:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO web_fetch_state(
                        source_id, etag, last_modified, last_attempt_at,
                        last_success_at, consecutive_failures, circuit_open_until
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (source_id) DO UPDATE SET
                        etag=EXCLUDED.etag,
                        last_modified=EXCLUDED.last_modified,
                        last_attempt_at=EXCLUDED.last_attempt_at,
                        last_success_at=EXCLUDED.last_success_at,
                        consecutive_failures=EXCLUDED.consecutive_failures,
                        circuit_open_until=EXCLUDED.circuit_open_until
                    """,
                    (
                        state.source_id,
                        state.etag,
                        state.last_modified,
                        state.last_attempt_at,
                        state.last_success_at,
                        state.consecutive_failures,
                        state.circuit_open_until,
                    ),
                )

    async def append_web_fetch_audit(self, audit: WebFetchAudit) -> bool:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO web_fetch_audit(
                        audit_id, source_id, requested_url, attempted_at, outcome,
                        status_code, bytes_received, response_sha256, error_code
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (audit_id) DO NOTHING
                    """,
                    (
                        audit.audit_id,
                        audit.source_id,
                        audit.requested_url,
                        audit.attempted_at,
                        audit.outcome.value,
                        audit.status_code,
                        audit.bytes_received,
                        audit.response_sha256,
                        audit.error_code,
                    ),
                )
                return cursor.rowcount == 1

    async def web_fetch_audits(
        self, *, source_id: str, limit: int = 100
    ) -> tuple[WebFetchAudit, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("Web fetch audit limit must be between 1 and 500.")
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    SELECT * FROM web_fetch_audit
                    WHERE source_id = %s
                    ORDER BY attempted_at DESC, audit_id DESC
                    LIMIT %s
                    """,
                    (source_id, limit),
                )
                rows = await cursor.fetchall()
        return tuple(_audit(row) for row in rows)


def _state(row: dict[str, Any]) -> WebFetchState:
    return WebFetchState(
        source_id=str(row["source_id"]),
        etag=cast(str | None, row["etag"]),
        last_modified=cast(str | None, row["last_modified"]),
        last_attempt_at=cast(datetime | None, row["last_attempt_at"]),
        last_success_at=cast(datetime | None, row["last_success_at"]),
        consecutive_failures=int(row["consecutive_failures"]),
        circuit_open_until=cast(datetime | None, row["circuit_open_until"]),
    )


def _audit(row: dict[str, Any]) -> WebFetchAudit:
    return WebFetchAudit(
        audit_id=str(row["audit_id"]),
        source_id=str(row["source_id"]),
        requested_url=str(row["requested_url"]),
        attempted_at=cast(datetime, row["attempted_at"]),
        outcome=WebFetchOutcome(str(row["outcome"])),
        status_code=cast(int | None, row["status_code"]),
        bytes_received=int(row["bytes_received"]),
        response_sha256=cast(str | None, row["response_sha256"]),
        error_code=cast(str | None, row["error_code"]),
    )
