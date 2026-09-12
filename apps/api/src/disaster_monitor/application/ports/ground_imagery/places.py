"""Bounded administrative place-boundary lookup contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from disaster_monitor.domain.imagery.regions import MultiPolygon, RegionSource


class PlaceBoundaryLookupError(RuntimeError):
    """A bounded boundary lookup could not be completed."""


@dataclass(frozen=True, slots=True)
class PlaceBoundary:
    """One pinned geoBoundaries administrative result."""

    boundary_id: str
    name: str
    country_code: str
    admin_level: int
    represented_year: int
    geometry: MultiPolygon
    source: RegionSource
    static_revision: str
    checksum: str

    def __post_init__(self) -> None:
        if not self.boundary_id.strip() or not self.name.strip():
            raise ValueError("A place boundary requires stable identity and name.")
        if self.admin_level not in {1, 2}:
            raise ValueError("Imagery place lookup supports ADM1 and ADM2 only.")
        if not self.static_revision.strip() or not self.checksum.strip():
            raise ValueError("A place boundary requires pinned revision and checksum.")


class PlaceBoundaryLookup(Protocol):
    async def find(
        self, *, name: str, country_code: str, admin_context: str | None = None
    ) -> tuple[PlaceBoundary, ...]: ...
