"""PostgreSQL persistence for versioned ground-imagery request metadata."""

from __future__ import annotations

import json
from typing import Any

import psycopg
from psycopg.rows import dict_row

from disaster_monitor.application.ground_imagery.models import GroundImageryRequest
from disaster_monitor.application.ports.ground_imagery.repository import (
    GroundImageryRequestStore,
)
from disaster_monitor.application.ports.ground_imagery.repository_codec import (
    request_from_document,
    request_to_document,
)
from disaster_monitor.application.ports.ground_imagery.selection_identity import (
    stable_selection_id,
)


class GroundImageryPersistenceError(RuntimeError):
    """Durable imagery metadata could not be read or written safely."""


class PostgresGroundImageryRequestStore(GroundImageryRequestStore):
    """Persist the current request version while preserving immutable payloads.

    The complete typed request is retained in JSONB for forward-compatible
    reconstruction. Indexed columns support operational queries without making
    provider metadata or geometry part of the application model's SQL shape.
    Historical region, selection, observation, job, and artifact rows are
    written by the durable workflow in later stages; this store never mutates
    a request to an older version.
    """

    durable = True

    def __init__(self, dsn: str) -> None:
        if not dsn.strip():
            raise ValueError("PostgreSQL DSN must not be empty.")
        self._dsn = dsn

    async def get_request(self, request_id: str) -> GroundImageryRequest | None:
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    "SELECT payload FROM imagery_requests WHERE request_id = %s",
                    (request_id,),
                )
                row: dict[str, Any] | None = await cursor.fetchone()
        if row is None:
            return None
        try:
            return request_from_document(row["payload"])
        except (TypeError, ValueError, KeyError) as error:
            raise GroundImageryPersistenceError(
                "Stored ground-imagery request metadata is invalid."
            ) from error

    async def get_request_for_selection(
        self, selection_id_value: str
    ) -> GroundImageryRequest | None:
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    SELECT requests.payload
                    FROM imagery_selections AS selections
                    JOIN imagery_requests AS requests
                      ON requests.request_id = selections.request_id
                    WHERE selections.selection_id = %s
                    """,
                    (selection_id_value,),
                )
                row: dict[str, Any] | None = await cursor.fetchone()
        if row is None:
            return None
        try:
            return request_from_document(row["payload"])
        except (TypeError, ValueError, KeyError) as error:
            raise GroundImageryPersistenceError(
                "Stored ground-imagery request metadata is invalid."
            ) from error

    async def save_request(self, request: GroundImageryRequest) -> None:
        payload = request_to_document(request)
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO imagery_requests(
                        request_id, incident_id, owner_scope, request_version,
                        reference_time, state, payload, created_at, updated_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
                    ON CONFLICT (request_id) DO UPDATE SET
                        incident_id=EXCLUDED.incident_id,
                        owner_scope=EXCLUDED.owner_scope,
                        request_version=EXCLUDED.request_version,
                        reference_time=EXCLUDED.reference_time,
                        state=EXCLUDED.state,
                        payload=EXCLUDED.payload,
                        updated_at=EXCLUDED.updated_at
                    WHERE EXCLUDED.request_version >= imagery_requests.request_version
                    RETURNING request_id
                    """,
                    (
                        request.request_id,
                        request.incident_id,
                        request.owner_scope,
                        request.request_version,
                        request.reference_time,
                        request.state.value,
                        json.dumps(payload, separators=(",", ":")),
                        request.created_at,
                        request.updated_at,
                    ),
                )
                if await cursor.fetchone() is None:
                    return
                if request.selection is not None:
                    for sensor in request.requested_sensors:
                        for outcome in request.selection.for_sensor(sensor).selections:
                            observation = outcome.observation
                            if observation is None:
                                continue
                            selection_key = stable_selection_id(
                                request.request_id,
                                sensor.value,
                                outcome.role.value,
                                observation.identity.stable_key,
                            )
                            await cursor.execute(
                                """
                                INSERT INTO imagery_selections(
                                    selection_id, request_id, request_version,
                                    sensor, temporal_role, observation_id,
                                    pinned, payload
                                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                                ON CONFLICT (selection_id) DO UPDATE SET
                                    request_id=EXCLUDED.request_id,
                                    request_version=EXCLUDED.request_version,
                                    sensor=EXCLUDED.sensor,
                                    temporal_role=EXCLUDED.temporal_role,
                                    observation_id=EXCLUDED.observation_id,
                                    payload=EXCLUDED.payload
                                WHERE EXCLUDED.request_version >=
                                    imagery_selections.request_version
                                """,
                                (
                                    selection_key,
                                    request.request_id,
                                    request.request_version,
                                    sensor.value,
                                    outcome.role.value,
                                    observation.observation_id,
                                    False,
                                    json.dumps(
                                        {
                                            "selection_id": selection_key,
                                            "request_id": request.request_id,
                                            "request_version": request.request_version,
                                            "sensor": sensor.value,
                                            "role": outcome.role.value,
                                            "observation_id": (
                                                observation.observation_id
                                            ),
                                            "reason": outcome.reason.value,
                                        },
                                        separators=(",", ":"),
                                    ),
                                ),
                            )

    async def aclose(self) -> None:
        return None

    async def _connection(self) -> psycopg.AsyncConnection[Any]:
        return await psycopg.AsyncConnection.connect(self._dsn)
