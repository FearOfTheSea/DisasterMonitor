"""PostgreSQL adapter for separate typed historical memory."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row

from disaster_monitor.domain.memory import (
    MemoryAuthority,
    MemoryLifecycleStatus,
    MemoryRecord,
    MemoryType,
)


class PostgresMemoryRepository:
    def __init__(self, dsn: str) -> None:
        if not dsn.strip():
            raise ValueError("PostgreSQL DSN must not be empty.")
        self._dsn = dsn

    async def save(
        self,
        record: MemoryRecord,
        *,
        superseded_memory_ids: tuple[str, ...] = (),
    ) -> None:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO agent_memory(
                        memory_id, schema_version, memory_type, lifecycle_status,
                        summary, conversation_id, physical_event_id,
                        disaster_identifier, country_code, source_message_ids,
                        evidence_ids, world_state_version, created_at, confirmed_at,
                        expires_at, superseded_by_memory_id, deleted_at, authority,
                        may_satisfy_current_evidence
                    ) VALUES (
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,
                        %s,%s,%s,%s,%s
                    )
                    ON CONFLICT (memory_id) DO UPDATE SET
                        schema_version=EXCLUDED.schema_version,
                        memory_type=EXCLUDED.memory_type,
                        lifecycle_status=EXCLUDED.lifecycle_status,
                        summary=EXCLUDED.summary,
                        conversation_id=EXCLUDED.conversation_id,
                        physical_event_id=EXCLUDED.physical_event_id,
                        disaster_identifier=EXCLUDED.disaster_identifier,
                        country_code=EXCLUDED.country_code,
                        source_message_ids=EXCLUDED.source_message_ids,
                        evidence_ids=EXCLUDED.evidence_ids,
                        world_state_version=EXCLUDED.world_state_version,
                        confirmed_at=EXCLUDED.confirmed_at,
                        expires_at=EXCLUDED.expires_at,
                        superseded_by_memory_id=EXCLUDED.superseded_by_memory_id,
                        deleted_at=EXCLUDED.deleted_at,
                        authority=EXCLUDED.authority,
                        may_satisfy_current_evidence=(
                            EXCLUDED.may_satisfy_current_evidence
                        )
                    """,
                    _parameters(record),
                )
                if superseded_memory_ids:
                    await cursor.execute(
                        """
                        UPDATE agent_memory
                        SET lifecycle_status='superseded',
                            superseded_by_memory_id=%s
                        WHERE memory_id = ANY(%s) AND lifecycle_status='active'
                        """,
                        (record.memory_id, list(superseded_memory_ids)),
                    )

    async def get(self, memory_id: str) -> MemoryRecord | None:
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    "SELECT * FROM agent_memory WHERE memory_id=%s", (memory_id,)
                )
                row = await cursor.fetchone()
        return None if row is None else _record(row)

    async def list_for_scope(
        self, conversation_id: str, physical_event_id: str | None = None
    ) -> tuple[MemoryRecord, ...]:
        query = "SELECT * FROM agent_memory WHERE conversation_id=%s"
        parameters: tuple[object, ...]
        if physical_event_id is None:
            parameters = (conversation_id,)
        else:
            query += " AND physical_event_id=%s"
            parameters = (conversation_id, physical_event_id)
        query += " ORDER BY confirmed_at DESC, memory_id DESC"
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(query, parameters)
                rows = await cursor.fetchall()
        return tuple(_record(row) for row in rows)

    async def mark_superseded(
        self,
        memory_id: str,
        *,
        superseded_by_memory_id: str,
    ) -> bool:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE agent_memory
                    SET lifecycle_status='superseded', superseded_by_memory_id=%s
                    WHERE memory_id=%s AND lifecycle_status='active'
                    """,
                    (superseded_by_memory_id, memory_id),
                )
                return cursor.rowcount == 1

    async def mark_expired(self, memory_id: str) -> bool:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE agent_memory SET lifecycle_status='expired'
                    WHERE memory_id=%s AND lifecycle_status='active'
                      AND expires_at IS NOT NULL
                    """,
                    (memory_id,),
                )
                return cursor.rowcount == 1

    async def mark_deleted_for_conversation(
        self, conversation_id: str, *, deleted_at: datetime
    ) -> int:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE agent_memory
                    SET lifecycle_status='deleted', deleted_at=%s,
                        superseded_by_memory_id=NULL
                    WHERE conversation_id=%s AND lifecycle_status <> 'deleted'
                    """,
                    (deleted_at, conversation_id),
                )
                return cursor.rowcount

    async def _connection(self) -> psycopg.AsyncConnection[Any]:
        return await psycopg.AsyncConnection.connect(self._dsn)


def _parameters(record: MemoryRecord) -> tuple[object, ...]:
    return (
        record.memory_id,
        record.schema_version,
        record.memory_type.value,
        record.status.value,
        record.summary,
        record.conversation_id,
        record.physical_event_id,
        record.disaster_identifier,
        record.country_code,
        json.dumps(record.source_message_ids),
        json.dumps(record.evidence_ids),
        record.world_state_version,
        record.created_at,
        record.confirmed_at,
        record.expires_at,
        record.superseded_by_memory_id,
        record.deleted_at,
        record.authority.value,
        record.may_satisfy_current_evidence,
    )


def _record(row: dict[str, Any]) -> MemoryRecord:
    return MemoryRecord(
        memory_id=str(row["memory_id"]),
        schema_version=str(row["schema_version"]),
        memory_type=MemoryType(str(row["memory_type"])),
        status=MemoryLifecycleStatus(str(row["lifecycle_status"])),
        summary=str(row["summary"]),
        conversation_id=str(row["conversation_id"]),
        physical_event_id=cast(str | None, row["physical_event_id"]),
        disaster_identifier=cast(str | None, row["disaster_identifier"]),
        country_code=cast(str | None, row["country_code"]),
        source_message_ids=_strings(row["source_message_ids"]),
        evidence_ids=_strings(row["evidence_ids"]),
        world_state_version=cast(str | None, row["world_state_version"]),
        created_at=cast(datetime, row["created_at"]),
        confirmed_at=cast(datetime, row["confirmed_at"]),
        expires_at=cast(datetime | None, row["expires_at"]),
        superseded_by_memory_id=cast(str | None, row["superseded_by_memory_id"]),
        deleted_at=cast(datetime | None, row["deleted_at"]),
        authority=MemoryAuthority(str(row["authority"])),
        may_satisfy_current_evidence=bool(row["may_satisfy_current_evidence"]),
    )


def _strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError("Stored memory identifier list is malformed.")
    return tuple(value)
