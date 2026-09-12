"""PostgreSQL persistence for the latest incident projection snapshots."""

from __future__ import annotations

from typing import Any

from psycopg.rows import dict_row

from disaster_monitor.application.ports.incident_projection import (
    IncidentProjectionRecord,
)
from disaster_monitor.infrastructure.operations.postgres_repository_base import (
    PostgresRepositoryBase,
)


class PostgresIncidentProjectionRepository(PostgresRepositoryBase):
    """Persist idempotent incident projection versions and their payloads."""

    async def append_incident_projection(
        self, projection: IncidentProjectionRecord
    ) -> bool:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO incident_projection(
                        projection_id, snapshot_version, retrieved_at,
                        created_at, payload
                    ) VALUES (%s,%s,%s,%s,%s::jsonb)
                    ON CONFLICT (projection_id) DO NOTHING
                    """,
                    (
                        projection.projection_id,
                        projection.snapshot_version,
                        projection.retrieved_at,
                        projection.created_at,
                        projection.payload_json,
                    ),
                )
                return cursor.rowcount == 1

    async def latest_incident_projection(
        self,
    ) -> IncidentProjectionRecord | None:
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    SELECT projection_id, snapshot_version, retrieved_at,
                           created_at, payload::text AS payload_json
                    FROM incident_projection
                    ORDER BY retrieved_at DESC, projection_id DESC
                    LIMIT 1
                    """
                )
                row = await cursor.fetchone()
        return None if row is None else incident_projection_from_row(row)


def incident_projection_from_row(row: dict[str, Any]) -> IncidentProjectionRecord:
    """Map one incident projection row at the persistence boundary."""
    return IncidentProjectionRecord(
        projection_id=str(row["projection_id"]),
        snapshot_version=str(row["snapshot_version"]),
        retrieved_at=row["retrieved_at"],
        created_at=row["created_at"],
        payload_json=str(row["payload_json"]),
    )
