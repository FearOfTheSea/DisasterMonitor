"""Read-only incident context consumed by imagery planning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from disaster_monitor.domain.disaster import Disaster, IncidentActivityStatus
from disaster_monitor.domain.imagery.observations import ImpactOnset
from disaster_monitor.domain.imagery.regions import Coordinate, RegionEvidence


@dataclass(frozen=True, slots=True)
class IncidentImageryContext:
    """The minimum read-only event context needed by the resolver."""

    incident_id: str
    disaster: Disaster
    country_code: str | None
    event_time: datetime
    evidence: tuple[RegionEvidence, ...] = ()
    verified_point: Coordinate | None = None
    onset: ImpactOnset | None = None
    impact_end: datetime | None = None
    activity_status: IncidentActivityStatus = IncidentActivityStatus.UNKNOWN
    reported_places: tuple[str, ...] = ()
    modeled_hazard_is_land_impact: bool = False
    verified_point_is_land_impact: bool = False

    def __post_init__(self) -> None:
        if not self.incident_id.strip():
            raise ValueError("An imagery context requires an incident ID.")
        if self.event_time.tzinfo is None or self.event_time.utcoffset() is None:
            raise ValueError("An imagery context event time must be timezone-aware.")
        if self.country_code is not None:
            normalized = self.country_code.strip().upper()
            if len(normalized) != 3 or not normalized.isalpha():
                raise ValueError("An imagery context country code must be ISO alpha-3.")
            object.__setattr__(self, "country_code", normalized)


class IncidentImageryContextReader(Protocol):
    """Expose only the incident evidence needed to plan an inspection."""

    async def get_imagery_context(
        self, incident_id: str
    ) -> IncidentImageryContext | None: ...
