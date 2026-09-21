"""Project admitted incident read models into the imagery context port."""

from __future__ import annotations

import logging
from dataclasses import replace

from disaster_monitor.application.earthquake_context import EarthquakeContextService
from disaster_monitor.application.ground_imagery.impact_regions import (
    shakemap_source_regions,
)
from disaster_monitor.application.incidents.active_incidents import (
    ActiveIncidentsQuery,
    ActiveIncidentsService,
)
from disaster_monitor.application.ports.ground_imagery.incidents import (
    IncidentImageryContext,
    IncidentImageryContextReader,
)
from disaster_monitor.domain.disaster import Disaster, ObservationKind
from disaster_monitor.domain.events import EventGeometryKind
from disaster_monitor.domain.imagery.observations import ImpactOnset
from disaster_monitor.domain.imagery.regions import (
    AssociationStatus,
    Coordinate,
    RegionEvidence,
    RegionSource,
    RegionSourceKind,
    polygon_from_geojson,
)

logger = logging.getLogger(__name__)


class ActiveIncidentImageryContextReader(IncidentImageryContextReader):
    """Find one already-admitted incident and expose no provider internals."""

    def __init__(self, incidents: ActiveIncidentsService) -> None:
        self._incidents = incidents

    async def get_imagery_context(
        self, incident_id: str
    ) -> IncidentImageryContext | None:
        snapshot = await self._incidents.execute(
            ActiveIncidentsQuery(
                time_window_days=30,
                limit_per_disaster=20,
                acquisition_limit_per_disaster=100,
                search=incident_id,
            )
        )
        incident = next(
            (item for item in snapshot.incidents if item.event_id == incident_id),
            None,
        )
        if incident is None:
            return None

        evidence: list[RegionEvidence] = []
        verified_point: Coordinate | None = None
        geometry = incident.geometry
        if geometry is not None and geometry.kind is EventGeometryKind.AREA:
            coordinates = [
                [coordinate.longitude, coordinate.latitude]
                for coordinate in geometry.coordinates
            ]
            if coordinates and coordinates[0] != coordinates[-1]:
                coordinates.append(coordinates[0])
            try:
                area = polygon_from_geojson(
                    {"type": "Polygon", "coordinates": [coordinates]}
                )
            except (TypeError, ValueError):
                area = None
            if area is not None:
                source_kind = (
                    RegionSourceKind.MODELED_HAZARD
                    if geometry.estimated
                    else RegionSourceKind.MAPPED_IMPACT
                )
                evidence.append(
                    RegionEvidence(
                        evidence_id=f"event-geometry:{incident.event_id}",
                        geometry=area,
                        source=RegionSource(
                            source_id=incident.source.source_id,
                            source_kind=source_kind,
                            publisher=incident.source.publisher,
                            reference=incident.source.canonical_url,
                            captured_at=incident.source.retrieved_at,
                            attribution=incident.source.publisher,
                        ),
                        association=(
                            AssociationStatus.POSSIBLE
                            if geometry.estimated
                            else AssociationStatus.CONFIRMED
                        ),
                        semantic_role=(
                            "modeled event geography"
                            if geometry.estimated
                            else "source event geography"
                        ),
                    )
                )
        elif geometry is not None and geometry.kind is EventGeometryKind.POINT:
            coordinate = geometry.coordinates[0]
            if not geometry.estimated:
                verified_point = Coordinate(coordinate.latitude, coordinate.longitude)

        onset = None
        if (
            incident.observation_kind is ObservationKind.PHYSICAL_EVENT
            and incident.disaster is not Disaster.TROPICAL_CYCLONE
        ):
            onset = ImpactOnset.exact(
                incident.event_time,
                source_id=incident.source.source_id,
            )
        return IncidentImageryContext(
            incident_id=incident.event_id,
            disaster=incident.disaster,
            country_code=(incident.country.country_code if incident.country else None),
            event_time=incident.event_time,
            evidence=tuple(evidence),
            verified_point=verified_point,
            onset=onset,
            activity_status=incident.activity_status,
            reported_places=(incident.location,) if incident.location.strip() else (),
        )


class EarthquakeProductImageryContextReader(IncidentImageryContextReader):
    """Enrich earthquake contexts with bounded authoritative ShakeMap coverage."""

    def __init__(
        self,
        base: IncidentImageryContextReader,
        earthquake_context: EarthquakeContextService,
    ) -> None:
        self._base = base
        self._earthquake_context = earthquake_context

    async def get_imagery_context(
        self, incident_id: str
    ) -> IncidentImageryContext | None:
        context = await self._base.get_imagery_context(incident_id)
        if context is None or context.disaster is not Disaster.EARTHQUAKE:
            return context
        usgs_event_id = incident_id.removeprefix("usgs:")
        if not incident_id.startswith("usgs:") or not usgs_event_id.isalnum():
            return context
        try:
            products = await self._earthquake_context.execute(incident_id)
        except Exception:
            logger.exception(
                "USGS earthquake products were unavailable for Ground region planning"
            )
            return context
        shaking_regions = shakemap_source_regions(products.shakemap_layers)
        if not shaking_regions:
            return context
        return replace(context, evidence=(*shaking_regions, *context.evidence))


__all__ = [
    "ActiveIncidentImageryContextReader",
    "EarthquakeProductImageryContextReader",
]
