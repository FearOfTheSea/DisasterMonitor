"""Application port for explicit provider request budgets."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ProviderBudgetReservation:
    reservation_id: str
    provider_id: str
    worker_id: str
    budget_window: str
    estimated_units: int
    reserved_at: datetime


@dataclass(frozen=True, slots=True)
class ProviderBudgetStatus:
    provider_id: str
    budget_window: str
    limit_units: int
    reserved_units: int
    settled_units: int
    released_units: int
    remaining_units: int
    reset_at: datetime


class ProviderBudgetExceeded(RuntimeError):
    """A bounded provider request would exceed the configured free budget."""


class ProviderBudgetLedger(Protocol):
    async def reserve(
        self,
        provider_id: str,
        *,
        worker_id: str,
        estimated_units: int,
        limit_units: int,
        now: datetime,
    ) -> ProviderBudgetReservation: ...

    async def settle(
        self,
        reservation_id: str,
        *,
        actual_units: int,
        now: datetime,
    ) -> None: ...

    async def release(self, reservation_id: str, *, now: datetime) -> None: ...

    async def status(self, *, now: datetime) -> tuple[ProviderBudgetStatus, ...]: ...
