"""PostgreSQL/PostGIS operational repository with SKIP LOCKED queue claims."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row

from disaster_monitor.domain.disaster import (
    Disaster,
    IncidentChangeKind,
    IncidentWatch,
    IncidentWatchChange,
    IncidentWatchObservation,
    IncidentWatchScope,
    WatchCoverageState,
    WatchScopeKind,
    watch_incident_document,
    watch_incident_from_document,
)
from disaster_monitor.domain.operations import (
    AuditEventRecord,
    EventObservationLinkRecord,
    IngestJob,
    IngestJobStatus,
    NormalizedObservationRecord,
    OperatorActionRecord,
    PhysicalEventRecord,
    ProviderFreshness,
    SourceSnapshotRecord,
    WorldStateVersionRecord,
    freshness_for,
)


class PostgresOperationalRepository:
    """Transactional adapter for the minimal persistent Roadmap-2 schema."""

    def __init__(self, dsn: str) -> None:
        if not dsn.strip():
            raise ValueError("PostgreSQL DSN must not be empty.")
        self._dsn = dsn

    async def migrate(self, migrations_root: Path | None = None) -> None:
        root = migrations_root or Path(__file__).with_name("migrations")
        scripts = sorted(root.glob("*.sql"))
        if not scripts:
            raise RuntimeError("No operational database migrations were found.")
        async with await self._connection() as connection:
            for path in scripts:
                version = path.stem
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS schema_migration (
                            version text PRIMARY KEY,
                            applied_at timestamptz NOT NULL DEFAULT now()
                        )
                        """
                    )
                    await cursor.execute(
                        "SELECT 1 FROM schema_migration WHERE version = %s", (version,)
                    )
                    if await cursor.fetchone() is not None:
                        continue
                    await cursor.execute(path.read_text(encoding="utf-8"))
                    await cursor.execute(
                        "INSERT INTO schema_migration(version) VALUES (%s)", (version,)
                    )

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

    async def claim(self, worker_id: str, *, now: datetime) -> IngestJob | None:
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    WITH candidate AS (
                        SELECT job_id FROM ingest_job
                        WHERE status IN ('queued', 'retry') AND scheduled_for <= %s
                        ORDER BY scheduled_for, job_id
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE ingest_job AS job
                    SET status='running', claimed_by=%s, claimed_at=%s,
                        attempt_count=attempt_count+1
                    FROM candidate
                    WHERE job.job_id=candidate.job_id
                    RETURNING job.*
                    """,
                    (now, worker_id, now),
                )
                row = await cursor.fetchone()
                return None if row is None else _job(row)

    async def complete(self, job_id: str, *, completed_at: datetime) -> None:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE ingest_job SET status='succeeded', completed_at=%s,
                        claimed_by=NULL, claimed_at=NULL
                    WHERE job_id=%s AND status='running'
                    """,
                    (completed_at, job_id),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("Only a running ingest job can complete.")

    async def fail(
        self,
        job_id: str,
        *,
        failed_at: datetime,
        error_code: str,
        retry_at: datetime,
    ) -> IngestJobStatus:
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    UPDATE ingest_job
                    SET status=CASE WHEN attempt_count >= max_attempts
                                    THEN 'dead_letter' ELSE 'retry' END,
                        scheduled_for=CASE WHEN attempt_count >= max_attempts
                                           THEN scheduled_for ELSE %s END,
                        last_error_code=%s, last_failed_at=%s,
                        claimed_by=NULL, claimed_at=NULL
                    WHERE job_id=%s AND status='running'
                    RETURNING status
                    """,
                    (retry_at, error_code, failed_at, job_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise RuntimeError("Only a running ingest job can fail.")
                return IngestJobStatus(str(row["status"]))

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
        return None if row is None else _snapshot(row)

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

    async def record_operator_action(self, action: OperatorActionRecord) -> bool:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO operator_action(
                        action_id, operator_id, decision, state_version, rationale,
                        evidence_ids, policy_ids, reviewed_at
                    ) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s)
                    ON CONFLICT (action_id) DO NOTHING
                    """,
                    (
                        action.action_id,
                        action.operator_id,
                        action.decision.value,
                        action.state_version,
                        action.rationale,
                        json.dumps(action.evidence_ids),
                        json.dumps(action.policy_ids),
                        action.reviewed_at,
                    ),
                )
                return cursor.rowcount == 1

    async def append_audit_event(self, event: AuditEventRecord) -> bool:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO audit_event(
                        audit_id, event_type, subject_id, occurred_at,
                        evidence_ids, policy_ids, public_rationale
                    ) VALUES (%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s)
                    ON CONFLICT (audit_id) DO NOTHING
                    """,
                    (
                        event.audit_id,
                        event.event_type,
                        event.subject_id,
                        event.occurred_at,
                        json.dumps(event.evidence_ids),
                        json.dumps(event.policy_ids),
                        event.public_rationale,
                    ),
                )
                return cursor.rowcount == 1

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
        return tuple(_snapshot(row) for row in rows)

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

    async def freshness(
        self,
        *,
        now: datetime,
        expectations: dict[str, timedelta],
    ) -> tuple[ProviderFreshness, ...]:
        results: list[ProviderFreshness] = []
        for source_id, expected in sorted(expectations.items()):
            snapshots = await self.snapshots(source_id=source_id, limit=1)
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
                    row = await cursor.fetchone()
            job = row
            failed = bool(job and job["status"] in {"retry", "dead_letter"})
            results.append(
                freshness_for(
                    source_id=source_id,
                    now=now,
                    expected_freshness=expected,
                    last_attempt_at=(
                        cast(datetime, job["claimed_at"] or job["created_at"])
                        if job
                        else None
                    ),
                    last_snapshot=snapshots[0] if snapshots else None,
                    consecutive_failures=1 if failed else 0,
                    latest_error_code=(
                        cast(str | None, job["last_error_code"]) if job else None
                    ),
                )
            )
        return tuple(results)

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

    async def create_watch(self, watch: IncidentWatch) -> bool:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO incident_watch(
                        watch_id, disaster, scope_kind, country_code, country_name,
                        enabled, refresh_interval_seconds, created_at, updated_at,
                        next_refresh_at, last_checked_at, coverage_state
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (watch_id) DO NOTHING
                    """,
                    (
                        watch.watch_id,
                        watch.disaster.value,
                        watch.scope.kind.value,
                        watch.scope.country_code,
                        watch.scope.country_name,
                        watch.enabled,
                        watch.refresh_interval_seconds,
                        watch.created_at,
                        watch.updated_at,
                        watch.next_refresh_at,
                        watch.last_checked_at,
                        watch.coverage_state.value if watch.coverage_state else None,
                    ),
                )
                return cursor.rowcount == 1

    async def list_watches(self) -> tuple[IncidentWatch, ...]:
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    _WATCH_SELECT + " GROUP BY watch.watch_id "
                    "ORDER BY watch.created_at DESC, watch.watch_id DESC"
                )
                rows = await cursor.fetchall()
        return tuple(_watch(row) for row in rows)

    async def get_watch(self, watch_id: str) -> IncidentWatch | None:
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    _WATCH_SELECT + " WHERE watch.watch_id=%s GROUP BY watch.watch_id",
                    (watch_id,),
                )
                row = await cursor.fetchone()
        return None if row is None else _watch(row)

    async def set_watch_enabled(
        self,
        watch_id: str,
        *,
        enabled: bool,
        updated_at: datetime,
    ) -> IncidentWatch | None:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE incident_watch
                    SET enabled=%s, updated_at=%s,
                        next_refresh_at=CASE WHEN %s THEN %s ELSE next_refresh_at END
                    WHERE watch_id=%s
                    """,
                    (enabled, updated_at, enabled, updated_at, watch_id),
                )
                if cursor.rowcount == 0:
                    return None
        return await self.get_watch(watch_id)

    async def delete_watch(self, watch_id: str) -> bool:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "DELETE FROM incident_watch WHERE watch_id=%s", (watch_id,)
                )
                return cursor.rowcount == 1

    async def due_watches(self, *, now: datetime) -> tuple[IncidentWatch, ...]:
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    _WATCH_SELECT
                    + " WHERE watch.enabled=true AND watch.next_refresh_at<=%s "
                    "GROUP BY watch.watch_id "
                    "ORDER BY watch.next_refresh_at, watch.watch_id",
                    (now,),
                )
                rows = await cursor.fetchall()
        return tuple(_watch(row) for row in rows)

    async def latest_watch_observation(
        self, watch_id: str
    ) -> IncidentWatchObservation | None:
        return await self._watch_observation_for_pointer(
            watch_id, "latest_observation_id"
        )

    async def latest_successful_watch_observation(
        self, watch_id: str
    ) -> IncidentWatchObservation | None:
        return await self._watch_observation_for_pointer(
            watch_id, "latest_successful_observation_id"
        )

    async def _watch_observation_for_pointer(
        self, watch_id: str, pointer: str
    ) -> IncidentWatchObservation | None:
        if pointer not in {
            "latest_observation_id",
            "latest_successful_observation_id",
        }:
            raise ValueError("Unsupported watch observation pointer.")
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    f"""
                    SELECT observation.*
                    FROM incident_watch AS watch
                    JOIN incident_watch_observation AS observation
                      ON observation.observation_id=watch.{pointer}
                    WHERE watch.watch_id=%s
                    """,
                    (watch_id,),
                )
                row = await cursor.fetchone()
        return None if row is None else _watch_observation(row)

    async def record_watch_refresh(
        self,
        observation: IncidentWatchObservation,
        changes: tuple[IncidentWatchChange, ...],
    ) -> int:
        inserted = 0
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT refresh_interval_seconds FROM incident_watch "
                    "WHERE watch_id=%s FOR UPDATE",
                    (observation.watch_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise ValueError("Incident watch does not exist.")
                refresh_interval_seconds = int(row[0])
                await cursor.execute(
                    """
                    INSERT INTO incident_watch_observation(
                        observation_id, watch_id, observed_at, coverage_state,
                        incidents, provider_names, provider_source_ids,
                        warnings, state_hash,
                        successful, retryable
                    ) VALUES (
                        %s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s,%s
                    )
                    ON CONFLICT (observation_id) DO NOTHING
                    """,
                    (
                        observation.observation_id,
                        observation.watch_id,
                        observation.observed_at,
                        observation.coverage_state.value,
                        json.dumps(
                            [
                                watch_incident_document(item)
                                for item in observation.incidents
                            ]
                        ),
                        json.dumps(observation.provider_names),
                        json.dumps(observation.provider_source_ids),
                        json.dumps(observation.warnings),
                        observation.state_hash,
                        observation.successful,
                        observation.retryable,
                    ),
                )
                for change in changes:
                    if change.watch_id != observation.watch_id:
                        raise ValueError("Watch change belongs to a different watch.")
                    await cursor.execute(
                        """
                        INSERT INTO incident_watch_change(
                            change_id, watch_id, kind, summary, detail, occurred_at,
                            source_ids, observation_id, previous_observation_id,
                            before_hash, after_hash, incident, read_at
                        ) VALUES (
                            %s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s::jsonb,%s
                        ) ON CONFLICT (change_id) DO NOTHING
                        """,
                        (
                            change.change_id,
                            change.watch_id,
                            change.kind.value,
                            change.summary,
                            change.detail,
                            change.created_at,
                            json.dumps(change.source_ids),
                            change.observation_id,
                            change.previous_observation_id,
                            change.before_hash,
                            change.after_hash,
                            (
                                json.dumps(watch_incident_document(change.incident))
                                if change.incident is not None
                                else None
                            ),
                            change.read_at,
                        ),
                    )
                    inserted += cursor.rowcount
                await cursor.execute(
                    """
                    UPDATE incident_watch
                    SET updated_at=%s, last_checked_at=%s,
                        next_refresh_at=%s + make_interval(secs => %s),
                        coverage_state=%s, latest_observation_id=%s,
                        latest_successful_observation_id=CASE
                            WHEN %s THEN %s ELSE latest_successful_observation_id END
                    WHERE watch_id=%s
                    """,
                    (
                        observation.observed_at,
                        observation.observed_at,
                        observation.observed_at,
                        refresh_interval_seconds,
                        observation.coverage_state.value,
                        observation.observation_id,
                        observation.successful,
                        observation.observation_id,
                        observation.watch_id,
                    ),
                )
        return inserted

    async def watch_changes(
        self, watch_id: str, *, limit: int = 100
    ) -> tuple[IncidentWatchChange, ...]:
        if limit < 1 or limit > 500:
            raise ValueError("Watch timeline limit must be between 1 and 500.")
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    SELECT * FROM incident_watch_change
                    WHERE watch_id=%s
                    ORDER BY occurred_at DESC, change_id DESC LIMIT %s
                    """,
                    (watch_id, limit),
                )
                rows = await cursor.fetchall()
        return tuple(_watch_change(row) for row in rows)

    async def mark_watch_changes_read(
        self,
        watch_id: str,
        change_ids: tuple[str, ...],
        *,
        read_at: datetime,
    ) -> int:
        query = (
            "UPDATE incident_watch_change SET read_at=%s "
            "WHERE watch_id=%s AND read_at IS NULL"
        )
        parameters: tuple[object, ...] = (read_at, watch_id)
        if change_ids:
            query += " AND change_id=ANY(%s)"
            parameters = (read_at, watch_id, list(change_ids))
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(query, parameters)
                return cursor.rowcount

    async def _connection(self) -> psycopg.AsyncConnection[Any]:
        return await psycopg.AsyncConnection.connect(self._dsn)


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
    )


def _snapshot(row: dict[str, Any]) -> SourceSnapshotRecord:
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


_WATCH_SELECT = """
SELECT watch.*, COUNT(change.change_id) FILTER (WHERE change.read_at IS NULL)
       AS unread_change_count
FROM incident_watch AS watch
LEFT JOIN incident_watch_change AS change ON change.watch_id=watch.watch_id
"""


def _watch(row: dict[str, Any]) -> IncidentWatch:
    kind = WatchScopeKind(str(row["scope_kind"]))
    scope = (
        IncidentWatchScope.worldwide()
        if kind is WatchScopeKind.WORLDWIDE
        else IncidentWatchScope.country(
            str(row["country_code"]), str(row["country_name"])
        )
    )
    coverage_value = cast(str | None, row["coverage_state"])
    return IncidentWatch(
        watch_id=str(row["watch_id"]),
        disaster=Disaster(str(row["disaster"])),
        scope=scope,
        enabled=bool(row["enabled"]),
        refresh_interval_seconds=int(row["refresh_interval_seconds"]),
        created_at=cast(datetime, row["created_at"]),
        updated_at=cast(datetime, row["updated_at"]),
        next_refresh_at=cast(datetime, row["next_refresh_at"]),
        last_checked_at=cast(datetime | None, row["last_checked_at"]),
        coverage_state=(
            WatchCoverageState(coverage_value) if coverage_value is not None else None
        ),
        unread_change_count=int(row["unread_change_count"]),
    )


def _watch_observation(row: dict[str, Any]) -> IncidentWatchObservation:
    return IncidentWatchObservation(
        observation_id=str(row["observation_id"]),
        watch_id=str(row["watch_id"]),
        observed_at=cast(datetime, row["observed_at"]),
        coverage_state=WatchCoverageState(str(row["coverage_state"])),
        incidents=tuple(
            watch_incident_from_document(item)
            for item in cast(list[object], row["incidents"])
        ),
        provider_names=tuple(
            str(item) for item in cast(list[object], row["provider_names"])
        ),
        warnings=tuple(str(item) for item in cast(list[object], row["warnings"])),
        state_hash=str(row["state_hash"]),
        successful=bool(row["successful"]),
        retryable=bool(row["retryable"]),
        provider_source_ids=tuple(
            str(item) for item in cast(list[object], row["provider_source_ids"])
        ),
    )


def _watch_change(row: dict[str, Any]) -> IncidentWatchChange:
    incident_value = row["incident"]
    return IncidentWatchChange(
        change_id=str(row["change_id"]),
        watch_id=str(row["watch_id"]),
        kind=IncidentChangeKind(str(row["kind"])),
        summary=str(row["summary"]),
        detail=str(row["detail"]),
        created_at=cast(datetime, row["occurred_at"]),
        source_ids=tuple(str(item) for item in cast(list[object], row["source_ids"])),
        observation_id=str(row["observation_id"]),
        previous_observation_id=cast(str | None, row["previous_observation_id"]),
        before_hash=cast(str | None, row["before_hash"]),
        after_hash=cast(str | None, row["after_hash"]),
        incident=(
            watch_incident_from_document(incident_value)
            if incident_value is not None
            else None
        ),
        read_at=cast(datetime | None, row["read_at"]),
    )
