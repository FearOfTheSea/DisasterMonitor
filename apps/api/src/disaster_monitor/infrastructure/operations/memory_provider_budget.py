"""Deterministic provider budget ledger used by local and test composition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from disaster_monitor.application.ports.provider_budget import (
    ProviderBudgetExceeded,
    ProviderBudgetReservation,
    ProviderBudgetStatus,
)


@dataclass
class _Window:
    provider_id: str
    window: str
    reset_at: datetime
    limit_units: int
    reserved_units: int = 0
    settled_units: int = 0
    released_units: int = 0


class InMemoryProviderBudgetLedger:
    """One-hour, per-provider accounting with idempotent settlement."""

    def __init__(self) -> None:
        self._windows: dict[tuple[str, str], _Window] = {}
        self._reservations: dict[str, ProviderBudgetReservation] = {}
        self._settled: set[str] = set()
        self._released: set[str] = set()

    async def reserve(
        self,
        provider_id: str,
        *,
        worker_id: str,
        estimated_units: int,
        limit_units: int,
        now: datetime,
    ) -> ProviderBudgetReservation:
        if not provider_id.strip() or not worker_id.strip():
            raise ValueError("Provider budget reservations require identities.")
        if estimated_units < 1 or limit_units < 1:
            raise ValueError("Provider budget units must be positive.")
        window = self._window_for(provider_id, now, limit_units)
        if (
            window.settled_units + window.reserved_units + estimated_units
            > window.limit_units
        ):
            raise ProviderBudgetExceeded(
                f"Provider budget exhausted for {provider_id} in {window.window}."
            )
        reservation_id = "provider-budget:" + uuid4().hex
        reservation = ProviderBudgetReservation(
            reservation_id=reservation_id,
            provider_id=provider_id,
            worker_id=worker_id,
            budget_window=window.window,
            estimated_units=estimated_units,
            reserved_at=now,
        )
        if reservation_id not in self._reservations:
            self._reservations[reservation_id] = reservation
            window.reserved_units += estimated_units
        return self._reservations[reservation_id]

    async def settle(
        self,
        reservation_id: str,
        *,
        actual_units: int,
        now: datetime,
    ) -> None:
        if actual_units < 0:
            raise ValueError("Actual provider budget units cannot be negative.")
        reservation = self._require(reservation_id)
        if reservation_id in self._settled or reservation_id in self._released:
            return
        window = self._reservation_window(reservation)
        window.settled_units += actual_units
        window.reserved_units = max(
            0, window.reserved_units - reservation.estimated_units
        )
        self._settled.add(reservation_id)

    async def release(self, reservation_id: str, *, now: datetime) -> None:
        reservation = self._require(reservation_id)
        if reservation_id in self._settled or reservation_id in self._released:
            return
        window = self._reservation_window(reservation)
        window.reserved_units = max(
            0, window.reserved_units - reservation.estimated_units
        )
        window.released_units += reservation.estimated_units
        self._released.add(reservation_id)

    async def status(self, *, now: datetime) -> tuple[ProviderBudgetStatus, ...]:
        values = []
        for window in sorted(self._windows.values(), key=lambda item: item.provider_id):
            if window.reset_at <= now:
                continue
            values.append(
                ProviderBudgetStatus(
                    provider_id=window.provider_id,
                    budget_window=window.window,
                    limit_units=window.limit_units,
                    reserved_units=window.reserved_units,
                    settled_units=window.settled_units,
                    released_units=window.released_units,
                    remaining_units=max(
                        0,
                        window.limit_units
                        - window.settled_units
                        - window.reserved_units,
                    ),
                    reset_at=window.reset_at,
                )
            )
        return tuple(values)

    def _require(self, reservation_id: str) -> ProviderBudgetReservation:
        try:
            return self._reservations[reservation_id]
        except KeyError as error:
            raise ValueError("Provider budget reservation was not found.") from error

    def _window_for(
        self, provider_id: str, now: datetime, limit_units: int | None
    ) -> _Window:
        timestamp = int(now.astimezone(UTC).timestamp()) // 3_600 * 3_600
        start = datetime.fromtimestamp(timestamp, tz=UTC)
        window_id = start.isoformat()
        key = (provider_id, window_id)
        current = self._windows.get(key)
        if current is None:
            if limit_units is None:
                raise RuntimeError("The provider budget window was not retained.")
            current = _Window(
                provider_id=provider_id,
                window=window_id,
                reset_at=start + timedelta(hours=1),
                limit_units=limit_units,
            )
            self._windows[key] = current
        elif limit_units is not None and current.limit_units != limit_units:
            raise ValueError("A provider budget limit cannot change mid-window.")
        return current

    def _reservation_window(self, reservation: ProviderBudgetReservation) -> _Window:
        try:
            return self._windows[(reservation.provider_id, reservation.budget_window)]
        except KeyError as error:
            raise RuntimeError(
                "The provider budget window was not retained."
            ) from error
