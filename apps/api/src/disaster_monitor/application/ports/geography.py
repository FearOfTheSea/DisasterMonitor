"""Ports and stable status types for deterministic country geography."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from disaster_monitor.domain.disaster import Country


class CountryCatalog(Protocol):
    """Resolve only exact canonical names, codes, and declared aliases."""

    def countries(self) -> tuple[Country, ...]: ...

    def find_mentions(self, text: str) -> tuple[Country, ...]: ...

    def get_by_alpha3(self, alpha3_code: str) -> Country | None: ...

    def contains(self, country: Country, latitude: float, longitude: float) -> bool: ...


class CountryCatalogUpdateState(StrEnum):
    """Public state of the autonomous catalog update process."""

    NEVER_RUN = "never_run"
    RUNNING = "running"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    FAILED = "failed"


class CountryCatalogUpdateTrigger(StrEnum):
    """Allowlisted reasons an update cycle may start."""

    MANUAL = "manual"
    SCHEDULED = "scheduled"
    SCRIPT = "script"


@dataclass(frozen=True, slots=True)
class CountryCatalogSourceVersion:
    """Version and checksum of one input admitted to a generated catalog."""

    source_id: str
    version: str
    revision: str
    sha256: str


@dataclass(frozen=True, slots=True)
class CountryCatalogUpdateStatus:
    """User-visible state without filesystem paths or internal exceptions."""

    state: CountryCatalogUpdateState
    active_version: str
    country_count: int
    automatic_updates_enabled: bool
    trigger: CountryCatalogUpdateTrigger | None = None
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    next_scheduled_at: datetime | None = None
    message: str = "The autonomous country catalog has not run yet."
    failure_code: str | None = None
    sources: tuple[CountryCatalogSourceVersion, ...] = ()


class CountryCatalogUpdateAutomation(Protocol):
    """Request, observe, and manage autonomous country catalog updates."""

    def status(self) -> CountryCatalogUpdateStatus: ...

    async def request_update(
        self, trigger: CountryCatalogUpdateTrigger
    ) -> CountryCatalogUpdateStatus: ...

    async def start(self) -> None: ...

    async def aclose(self) -> None: ...
