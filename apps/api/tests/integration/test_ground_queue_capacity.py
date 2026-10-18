"""Real-engine admission serialization; requires the dedicated PostgreSQL gate."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest

from disaster_monitor.application.ports.ground_imagery.jobs import (
    GroundImageryQueueFull,
    preparation_job,
)
from disaster_monitor.domain.imagery.observations import Sensor, TemporalRole
from disaster_monitor.infrastructure.ground_imagery.postgres_jobs import (
    PostgresGroundImageryJobQueue,
)
from disaster_monitor.infrastructure.operations.postgres_repository import (
    PostgresOperationalRepository,
)


@pytest.mark.postgres
async def test_postgres_queue_serializes_bounded_admission(postgres_dsn):
    await PostgresOperationalRepository(postgres_dsn).migrate()
    identifier = "queue-capacity:" + uuid4().hex
    now = datetime.now(UTC)
    async with await psycopg.AsyncConnection.connect(postgres_dsn) as connection:
        # A queue-boundary parent row: the queue does not decode request payloads.
        await connection.execute(
            "INSERT INTO imagery_requests(request_id,incident_id,owner_scope,"
            "request_version,reference_time,state,payload,created_at,updated_at) "
            "VALUES (%s,%s,'queue-fixture',1,%s,'ready','{}',%s,%s)",
            (identifier, identifier, now, now, now),
        )
        cursor = await connection.execute(
            "SELECT count(*) FROM imagery_jobs WHERE status IN "
            "('queued','running','retry_wait')"
        )
        count = await cursor.fetchone()
        assert count is not None
        bound = count[0] + 1
    queue = PostgresGroundImageryJobQueue(postgres_dsn, maximum_pending=bound)
    jobs = [
        preparation_job(
            request_id=identifier,
            request_version=1,
            sensor=sensor,
            role=TemporalRole.LATEST_USEFUL,
            overview=True,
            output_kind=None,
            now=now,
        )
        for sensor in (Sensor.SENTINEL_1, Sensor.SENTINEL_2)
    ]
    try:
        outcomes = await asyncio.gather(
            *(queue.enqueue(job) for job in jobs), return_exceptions=True
        )
        assert sum(outcome is True for outcome in outcomes) == 1
        assert (
            sum(isinstance(outcome, GroundImageryQueueFull) for outcome in outcomes)
            == 1
        )
        admitted = jobs[outcomes.index(True)]
        assert not await queue.enqueue(admitted)
    finally:
        async with await psycopg.AsyncConnection.connect(postgres_dsn) as connection:
            await connection.execute(
                "DELETE FROM imagery_requests WHERE request_id=%s", (identifier,)
            )
