"""Adapt admitted incident projections to the standalone evidence reader."""

from dataclasses import replace

from disaster_monitor.application.incidents.active_incidents import (
    ActiveIncidentsService,
)
from disaster_monitor.application.media import MediaEventContext
from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.application.ports.standalone_evidence import (
    IncidentEvidenceContext,
)
from disaster_monitor.domain.event_identifiers import (
    EventIdentifierRole,
    event_identifier_role,
)
from disaster_monitor.domain.events import DisasterEvent, EventGeometryKind
from disaster_monitor.domain.imagery.regions import polygon_from_geojson


class IncidentEvidenceContextReader:
    def __init__(
        self, incidents: ActiveIncidentsService, catalog: CountryCatalog
    ) -> None:
        self._incidents = incidents
        self._catalog = catalog

    async def read(self, identifier: str) -> IncidentEvidenceContext:
        incident = await self._incidents.lookup(identifier)
        time_known = (
            not incident.discovery_event
            or incident.discovery_event.event_time is not None
        )
        country = (
            self._catalog.get_by_alpha3(incident.country.country_code)
            if incident.country
            else None
        )
        coordinates = incident.geometry.coordinates if incident.geometry else ()
        first = coordinates[0] if coordinates else None
        area = None
        if incident.geometry and incident.geometry.kind is EventGeometryKind.AREA:
            ring = [[point.longitude, point.latitude] for point in coordinates]
            if ring and ring[0] != ring[-1]:
                ring.append(ring[0])
            try:
                area = polygon_from_geojson({"type": "Polygon", "coordinates": [ring]})
            except ValueError:
                pass
        media = MediaEventContext(
            incident.event_id,
            incident.physical_event_id or incident.event_id,
            incident.disaster,
            incident.location,
            incident.event_time,
            tuple(
                value
                for value in incident.provider_ids
                if event_identifier_role(value) is EventIdentifierRole.PHYSICAL_EVENT
            ),
            country.alpha3_code if country else None,
            (country.canonical_name, *country.aliases) if country else (),
            first.latitude if first else None,
            first.longitude if first else None,
            collected_articles=tuple(
                {
                    s.canonical_url: s
                    for r in incident.discovery_event.reports
                    for s in (
                        r.article.source,
                        *(
                            (
                                replace(
                                    r.article.source,
                                    canonical_url=r.article.original_url,
                                ),
                            )
                            if r.article.original_url
                            else ()
                        ),
                    )
                }.values()
            )
            if incident.discovery_event
            else (),
            event_time_known=time_known,
            multi_event_article_urls=tuple(
                url
                for r in incident.discovery_event.reports
                if (r.mention_count or len(r.mentions)) > 1
                for url in (r.article.source.canonical_url, r.article.original_url)
                if url
            )
            if incident.discovery_event
            else (),
        )
        event = (
            DisasterEvent(
                incident.event_id,
                incident.disaster,
                incident.location,
                country,
                incident.event_time,
                incident.source,
                geometry=incident.geometry,
                measurements=incident.measurements,
                provider_ids=incident.provider_ids,
                event_time_end=incident.event_time_end,
                event_time_precision=incident.event_time_precision,
                lineage_ids=incident.lineage_ids,
                provider_tier=incident.provider_tier,
                observation_kind=incident.observation_kind,
            )
            if country and time_known
            else None
        )
        return IncidentEvidenceContext(media, event, area)
