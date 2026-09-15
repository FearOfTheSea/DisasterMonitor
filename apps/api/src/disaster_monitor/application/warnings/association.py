"""Conservative warning-to-incident association policy."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.domain.imagery.regions import (
    MultiPolygon,
    geometries_intersect,
    polygon_from_geojson,
)
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


def associate_earthquake_tsunami_warning(
    warning: CapAlert,
    *,
    earthquake_event_id: str,
    earthquake_time: datetime,
    earthquake_latitude: float,
    earthquake_longitude: float,
    authoritative_source_ids: tuple[str, ...] = ("noaa-tsunami-warnings",),
    maximum_time_delta: timedelta = timedelta(hours=3),
) -> WarningAssociation | None:
    """Associate an official tsunami warning without claiming tsunami occurrence."""
    if warning.source_id not in authoritative_source_ids or not _is_tsunami(warning):
        return None
    normalized_event_id = earthquake_event_id.strip().casefold()
    if normalized_event_id and normalized_event_id in {
        item.strip().casefold() for item in warning.incidents
    }:
        return WarningAssociation(
            warning.identifier,
            earthquake_event_id,
            WarningAssociationBasis.EXPLICIT_INCIDENT_ID,
            True,
            "The authoritative tsunami warning explicitly references the earthquake "
            "event identifier; it does not confirm tsunami occurrence.",
        )
    delta = 0.01
    event_area = polygon_from_geojson(
        {
            "type": "Polygon",
            "coordinates": [
                [
                    [earthquake_longitude - delta, earthquake_latitude - delta],
                    [earthquake_longitude + delta, earthquake_latitude - delta],
                    [earthquake_longitude + delta, earthquake_latitude + delta],
                    [earthquake_longitude - delta, earthquake_latitude + delta],
                    [earthquake_longitude - delta, earthquake_latitude - delta],
                ]
            ],
        }
    )
    warning_times = tuple(
        value
        for info in warning.infos
        for value in (info.onset, info.effective, warning.sent)
        if value is not None
    )
    warning_geometries = tuple(
        geometry
        for info in warning.infos
        for area in info.areas
        for geometry in area.polygons
    )
    if (
        not warning_times
        or min(abs(value - earthquake_time) for value in warning_times)
        > maximum_time_delta
        or not any(
            geometries_intersect(event_area, geometry)
            for geometry in warning_geometries
        )
    ):
        return None
    return WarningAssociation(
        warning.identifier,
        earthquake_event_id,
        WarningAssociationBasis.TIME_AND_GEOMETRY,
        False,
        "Authoritative warning geography contains the earthquake epicenter and the "
        "message time is within three hours; this is a candidate association only.",
    )


def _is_tsunami(warning: CapAlert) -> bool:
    values = (
        *(info.event for info in warning.infos),
        *(
            value
            for info in warning.infos
            for name, value in info.event_codes
            if name.strip()
        ),
    )
    return any("tsunami" in value.casefold() for value in values)
