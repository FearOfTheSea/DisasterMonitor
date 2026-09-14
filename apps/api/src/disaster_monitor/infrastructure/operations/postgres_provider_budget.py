"""Transactional PostgreSQL provider-budget accounting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from psycopg.rows import dict_row

from disaster_monitor.application.ports.provider_budget import (
    ProviderBudgetExceeded,
    ProviderBudgetReservation,
    ProviderBudgetStatus,
)
from disaster_monitor.infrastructure.operations.postgres_repository_base import (
    PostgresRepositoryBase,
)


class PostgresProviderBudgetLedger(PostgresRepositoryBase):
    """Reserve before a provider call and settle/release exactly once."""

    def __init__(self, dsn: str) -> None:
        if not dsn.strip():
            raise ValueError("PostgreSQL DSN must not be empty.")
        self._dsn = dsn

    async def reserve(
        self,
        provider_id: str,
        *,
        worker_id: str,
        estimated_units: int,
        limit_units: int,
        now: datetime,
    ) -> ProviderBudgetReservation:
        if estimated_units < 1 or limit_units < 1:
            raise ValueError("Provider budget units must be positive.")
        window_start = _window_start(now)
        reset_at = window_start + timedelta(hours=1)
        reservation_id = "provider-budget:" + uuid4().hex
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    INSERT INTO provider_budget_window(
                        provider_id, window_start, reset_at, limit_units
                    ) VALUES (%s,%s,%s,%s)
                    ON CONFLICT (provider_id, window_start) DO NOTHING
                    """,
                    (provider_id, window_start, reset_at, limit_units),
                )
                await cursor.execute(
                    """
                    SELECT limit_units, reserved_units, settled_units
                    FROM provider_budget_window
                    WHERE provider_id=%s AND window_start=%s
                    FOR UPDATE
                    """,
                    (provider_id, window_start),
                )
                row: dict[str, Any] | None = await cursor.fetchone()
                if row is None:
                    raise RuntimeError(
                        "The provider budget window could not be locked."
                    )
                if int(row["limit_units"]) != limit_units:
                    raise ValueError(
                        "A provider budget limit cannot change mid-window."
                    )
                if (
                    int(row["settled_units"])
                    + int(row["reserved_units"])
                    + estimated_units
                    > limit_units
                ):
                    raise ProviderBudgetExceeded(
                        f"Provider budget exhausted for {provider_id}."
                    )
                await cursor.execute(
                    """
                    INSERT INTO provider_budget_reservation(
                        reservation_id, provider_id, worker_id, window_start,
                        estimated_units, status, reserved_at
                    ) VALUES (%s,%s,%s,%s,%s,'reserved',%s)
                    ON CONFLICT (reservation_id) DO NOTHING
                    """,
                    (
                        reservation_id,
                        provider_id,
                        worker_id,
                        window_start,
                        estimated_units,
                        now,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError(
                        "A provider budget reservation identity unexpectedly collided."
                    )
                await cursor.execute(
                    """
                    UPDATE provider_budget_window
                    SET reserved_units=reserved_units+%s
                    WHERE provider_id=%s AND window_start=%s
                    """,
                    (estimated_units, provider_id, window_start),
                )
        return ProviderBudgetReservation(
            reservation_id,
            provider_id,
            worker_id,
            window_start.isoformat(),
            estimated_units,
            now,
        )

    async def settle(
        self, reservation_id: str, *, actual_units: int, now: datetime
    ) -> None:
        if actual_units < 0:
            raise ValueError("Actual provider budget units cannot be negative.")
        await self._finish(reservation_id, "settled", actual_units, now)

    async def release(self, reservation_id: str, *, now: datetime) -> None:
        await self._finish(reservation_id, "released", 0, now)

    async def _finish(
        self, reservation_id: str, status: str, actual_units: int, now: datetime
    ) -> None:
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    SELECT provider_id, window_start, estimated_units, status
                    FROM provider_budget_reservation
                    WHERE reservation_id=%s FOR UPDATE
                    """,
                    (reservation_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise ValueError("Provider budget reservation was not found.")
                if str(row["status"]) != "reserved":
                    return
                estimated = int(row["estimated_units"])
                provider_id = str(row["provider_id"])
                window_start = row["window_start"]
                await cursor.execute(
                    """
                    UPDATE provider_budget_reservation
                    SET status=%s, settled_at=%s, actual_units=%s
                    WHERE reservation_id=%s
                    """,
                    (
                        status,
                        now,
                        actual_units if status == "settled" else None,
                        reservation_id,
                    ),
                )
                column = "settled_units" if status == "settled" else "released_units"
                await cursor.execute(
                    f"""UPDATE provider_budget_window
                        SET reserved_units=GREATEST(0, reserved_units-%s),
                            {column}={column}+%s
                        WHERE provider_id=%s AND window_start=%s""",
                    (
                        estimated,
                        actual_units if status == "settled" else estimated,
                        provider_id,
                        window_start,
                    ),
                )

    async def status(self, *, now: datetime) -> tuple[ProviderBudgetStatus, ...]:
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    SELECT provider_id, window_start, reset_at, limit_units,
                           reserved_units, settled_units, released_units
                    FROM provider_budget_window
                    WHERE reset_at > %s
                    ORDER BY provider_id, window_start
                    """,
                    (now,),
                )
                rows = await cursor.fetchall()
        return tuple(
            ProviderBudgetStatus(
                provider_id=str(row["provider_id"]),
                budget_window=cast_datetime(row["window_start"]).isoformat(),
                limit_units=int(row["limit_units"]),
                reserved_units=int(row["reserved_units"]),
                settled_units=int(row["settled_units"]),
                released_units=int(row["released_units"]),
                remaining_units=max(
                    0,
                    int(row["limit_units"])
                    - int(row["settled_units"])
                    - int(row["reserved_units"]),
                ),
                reset_at=cast_datetime(row["reset_at"]),
            )
            for row in rows
        )


def _window_start(now: datetime) -> datetime:
    timestamp = int(now.astimezone(UTC).timestamp()) // 3_600 * 3_600
    return datetime.fromtimestamp(timestamp, tz=UTC)


def cast_datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("Provider budget timestamps must be timezone-aware datetimes.")
    return value
