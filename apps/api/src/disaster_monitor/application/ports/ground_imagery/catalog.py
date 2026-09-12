"""Provider-neutral catalog search contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from disaster_monitor.domain.imagery.observations import (
    Observation,
    Sensor,
    TemporalRole,
)
from disaster_monitor.domain.imagery.regions import MultiPolygon


@dataclass(frozen=True, slots=True)
class GroundImageryCatalogQuery:
    """One bounded STAC/catalog search."""

    sensor: Sensor
    geometry: MultiPolygon
    start: datetime
    end: datetime
    role: TemporalRole
    limit: int = 100
    cursor: str | None = None

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.start.utcoffset() is None:
            raise ValueError("Catalog query start must be timezone-aware.")
        if self.end.tzinfo is None or self.end.utcoffset() is None:
            raise ValueError("Catalog query end must be timezone-aware.")
        if self.end < self.start:
            raise ValueError("Catalog query interval cannot be reversed.")
        if not 1 <= self.limit <= 100:
            raise ValueError("Catalog page size must be between 1 and 100.")
        if self.cursor is not None and not self.cursor.strip():
            raise ValueError("Catalog cursor must not be empty.")


@dataclass(frozen=True, slots=True)
class GroundImageryCatalogPage:
    """A bounded page with explicit truncation state."""

    observations: tuple[Observation, ...]
    next_cursor: str | None
    scanned_count: int
    scan_complete: bool
    source_revision: str | None = None

    def __post_init__(self) -> None:
        if self.scanned_count < len(self.observations):
            raise ValueError("Catalog scanned count cannot be below returned items.")
        if self.next_cursor is not None and not self.next_cursor.strip():
            raise ValueError("Catalog next cursor must not be empty.")


class CatalogSearchError(RuntimeError):
    """A provider failure distinct from an empty catalog result."""

    def __init__(self, message: str, *, reason_code: str, retryable: bool) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.retryable = retryable


class GroundImageryCatalog(Protocol):
    """Search real acquisition metadata without choosing a scene."""

    async def search(
        self, query: GroundImageryCatalogQuery
    ) -> GroundImageryCatalogPage: ...

    async def aclose(self) -> None: ...
