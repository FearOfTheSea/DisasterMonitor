"""PostgreSQL persistence for immutable snapshots and evidence world state."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from psycopg.rows import dict_row

from disaster_monitor.domain.operations import (
    EventObservationLinkRecord,
    NormalizedObservationRecord,
    PhysicalEventRecord,
    SourceSnapshotRecord,
    WorldStateVersionRecord,
)
from disaster_monitor.infrastructure.operations.postgres_repository_base import (
    PostgresRepositoryBase,
)


class PostgresIngestionEvidenceRepository(PostgresRepositoryBase):
    """Append-only snapshot, observation, and world-state persistence."""

    async def append_snapshot(self, snapshot: SourceSnapshotRecord) -> bool:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "INSERT INTO source(source_id, rights_id) VALUES (%s,%s) "
                    "ON CONFLICT (source_id) DO NOTHING",
                    (snapshot.source_id, snapshot.rights_id),
                )
                await cursor.execute(
                    """
                    INSERT INTO source_snapshot(
                        snapshot_id, idempotency_key, source_id,
                        canonical_request_identity, provider_revision, retrieved_at,
                        published_at, observed_at, response_status, content_type,
                        payload_sha256, payload_size_bytes, blob_uri, rights_id
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (idempotency_key) DO NOTHING
                    """,
                    (
                        snapshot.snapshot_id,
                        snapshot.idempotency_key,
                        snapshot.source_id,
                        snapshot.canonical_request_identity,
                        snapshot.provider_revision,
                        snapshot.retrieved_at,
                        snapshot.published_at,
                        snapshot.observed_at,
                        snapshot.response_status,
                        snapshot.content_type,
                        snapshot.payload_sha256,
                        snapshot.payload_size_bytes,
                        snapshot.blob_uri,
                        snapshot.rights_id,
                    ),
                )
                return cursor.rowcount == 1

    async def snapshot_by_idempotency_key(
        self, idempotency_key: str
    ) -> SourceSnapshotRecord | None:
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    "SELECT * FROM source_snapshot WHERE idempotency_key=%s",
                    (idempotency_key,),
                )
                row = await cursor.fetchone()
        return None if row is None else source_snapshot_from_row(row)

    async def append_observations(
        self, observations: tuple[NormalizedObservationRecord, ...]
    ) -> int:
        inserted = 0
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                for item in observations:
                    await cursor.execute(
                        """
                        INSERT INTO normalized_observation(
                            observation_id, snapshot_id, source_id, observation_type,
                            effective_at, parser_version, canonical_document
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)
                        ON CONFLICT (observation_id) DO NOTHING
                        """,
                        (
                            item.observation_id,
                            item.snapshot_id,
                            item.source_id,
                            item.observation_type,
                            item.effective_at,
                            item.parser_version,
                            item.canonical_json,
                        ),
                    )
                    inserted += cursor.rowcount
        return inserted

    async def append_world_state(self, state: WorldStateVersionRecord) -> bool:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO world_state_version(
                        state_version, physical_event_id, source_set_sha256,
                        canonical_state_sha256, policy_version, created_at
                    ) VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (state_version) DO NOTHING
                    """,
                    (
                        state.state_version,
                        state.physical_event_id,
                        state.source_set_sha256,
                        state.canonical_state_sha256,
                        state.policy_version,
                        state.created_at,
                    ),
                )
                return cursor.rowcount == 1

    async def append_physical_event(self, event: PhysicalEventRecord) -> bool:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                if event.longitude is None or event.latitude is None:
                    await cursor.execute(
                        """
                        INSERT INTO physical_event(
                            physical_event_id, disaster, country_code,
                            representative_geometry, created_at
                        ) VALUES (%s, %s, %s, NULL, %s)
                        ON CONFLICT (physical_event_id) DO NOTHING
                        """,
                        (
                            event.physical_event_id,
                            event.disaster,
                            event.country_code,
                            event.created_at,
                        ),
                    )
                else:
                    await cursor.execute(
                        """
                        INSERT INTO physical_event(
                            physical_event_id, disaster, country_code,
                            representative_geometry, created_at
                        ) VALUES (
                            %s, %s, %s,
                            ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                            %s
                        ) ON CONFLICT (physical_event_id) DO NOTHING
                        """,
                        (
                            event.physical_event_id,
                            event.disaster,
                            event.country_code,
                            event.longitude,
                            event.latitude,
                            event.created_at,
                        ),
                    )
                return cursor.rowcount == 1

    async def append_event_links(
        self, links: tuple[EventObservationLinkRecord, ...]
    ) -> int:
        inserted = 0
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                for link in links:
                    await cursor.execute(
                        """
                        INSERT INTO event_observation_link(
                            physical_event_id, observation_id,
                            assignment_status, rationale
                        ) VALUES (%s,%s,%s,%s)
                        ON CONFLICT (physical_event_id, observation_id) DO NOTHING
                        """,
                        (
                            link.physical_event_id,
                            link.observation_id,
                            link.assignment_status,
                            link.rationale,
                        ),
                    )
                    inserted += cursor.rowcount
        return inserted

    async def world_state_exists(self, state_version: str) -> bool:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT 1 FROM world_state_version WHERE state_version=%s",
                    (state_version,),
                )
                return await cursor.fetchone() is not None

    async def snapshots(
        self, *, source_id: str | None = None, limit: int = 100
    ) -> tuple[SourceSnapshotRecord, ...]:
        if limit < 1 or limit > 500:
            raise ValueError("Snapshot history limit must be between 1 and 500.")
        query = "SELECT * FROM source_snapshot"
        parameters: tuple[object, ...]
        if source_id is None:
            parameters = (limit,)
        else:
            query += " WHERE source_id=%s"
            parameters = (source_id, limit)
        query += " ORDER BY retrieved_at DESC, snapshot_id DESC LIMIT %s"
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(query, parameters)
                rows = await cursor.fetchall()
        return tuple(source_snapshot_from_row(row) for row in rows)

    async def tombstone_snapshot(
        self,
        snapshot_id: str,
        *,
        deleted_at: datetime,
        reason: str,
    ) -> bool:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE source_snapshot
                    SET content_deleted_at=%s, content_deletion_reason=%s
                    WHERE snapshot_id=%s AND content_deleted_at IS NULL
                    """,
                    (deleted_at, reason, snapshot_id),
                )
                return cursor.rowcount == 1


def source_snapshot_from_row(row: dict[str, Any]) -> SourceSnapshotRecord:
    """Map one source-snapshot row at the evidence persistence boundary."""
    return SourceSnapshotRecord(
        snapshot_id=str(row["snapshot_id"]),
        idempotency_key=str(row["idempotency_key"]),
        source_id=str(row["source_id"]),
        canonical_request_identity=str(row["canonical_request_identity"]),
        provider_revision=str(row["provider_revision"]),
        retrieved_at=cast(datetime, row["retrieved_at"]),
        published_at=cast(datetime | None, row["published_at"]),
        observed_at=cast(datetime | None, row["observed_at"]),
        response_status=int(row["response_status"]),
        content_type=str(row["content_type"]),
        payload_sha256=str(row["payload_sha256"]),
        payload_size_bytes=int(row["payload_size_bytes"]),
        blob_uri=str(row["blob_uri"]),
        rights_id=str(row["rights_id"]),
        content_deleted_at=cast(datetime | None, row["content_deleted_at"]),
        content_deletion_reason=cast(str | None, row["content_deletion_reason"]),
    )
