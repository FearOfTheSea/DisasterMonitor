"""Conservative warning-to-incident association policy."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.domain.imagery.regions import MultiPolygon, geometries_intersect
from disaster_monitor.domain.warnings import CapAlert


class WarningAssociationBasis(StrEnum):
    EXPLICIT_INCIDENT_ID = "explicit_incident_id"
    TIME_AND_GEOMETRY = "time_and_geometry"


@dataclass(frozen=True, slots=True)
class WarningAssociation:
    warning_identifier: str
    event_id: str
    basis: WarningAssociationBasis
    confirmed: bool
    rationale: str


def associate_warning(
    warning: CapAlert,
    *,
    disaster: Disaster,
    event_id: str,
    event_time: datetime,
    event_geometry: MultiPolygon | None,
    maximum_time_delta: timedelta = timedelta(hours=24),
) -> WarningAssociation | None:
    normalized_event_id = event_id.strip().casefold()
    if normalized_event_id and normalized_event_id in {
        item.strip().casefold() for item in warning.incidents
    }:
        return WarningAssociation(
            warning.identifier,
            event_id,
            WarningAssociationBasis.EXPLICIT_INCIDENT_ID,
            True,
            "The CAP incident identifier explicitly matches the physical event.",
        )
    if disaster not in warning.hazard_candidates or event_geometry is None:
        return None
    warning_times = tuple(
        value
        for info in warning.infos
        for value in (info.onset, info.effective, warning.sent)
        if value is not None
    )
    if (
        not warning_times
        or min(abs(value - event_time) for value in warning_times) > maximum_time_delta
    ):
        return None
    warning_geometries = tuple(
        geometry
        for info in warning.infos
        for area in info.areas
        for geometry in area.polygons
    )
    if not any(
        geometries_intersect(event_geometry, geometry)
        for geometry in warning_geometries
    ):
        return None
    return WarningAssociation(
        warning.identifier,
        event_id,
        WarningAssociationBasis.TIME_AND_GEOMETRY,
        False,
        "Hazard-compatible source geometry and validity time overlap; no explicit "
        "incident identifier was supplied.",
    )
