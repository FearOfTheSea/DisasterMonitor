"""PostgreSQL/PostGIS operational repository with SKIP LOCKED queue claims."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, cast

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
from disaster_monitor.infrastructure.operations.postgres_repository_base import (
    PostgresRepositoryBase,
)

_WATCH_SELECT = """
SELECT watch.*, COUNT(change.change_id) FILTER (WHERE change.read_at IS NULL)
       AS unread_change_count
FROM incident_watch AS watch
LEFT JOIN incident_watch_change AS change ON change.watch_id=watch.watch_id
"""


class PostgresIncidentWatchRepository(PostgresRepositoryBase):
    """Transactional persistence for incident-watch state and timelines."""

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
