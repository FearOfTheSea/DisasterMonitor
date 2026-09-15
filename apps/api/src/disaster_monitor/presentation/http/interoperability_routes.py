"""Credential-free deterministic interoperability endpoints."""

from dataclasses import asdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from disaster_monitor.application.evidence.provenance_graph import (
    ProvenanceGraphBuilder,
)
from disaster_monitor.application.evidence.why_evidence import ExplainEvidenceTrace
from disaster_monitor.application.incidents.active_incidents import (
    ActiveIncidentsService,
)
from disaster_monitor.application.incidents.manage_incident_watches import (
    IncidentWatchNotFoundError,
    ManageIncidentWatches,
)
from disaster_monitor.application.interoperability.exports import (
    export_findings_csv,
    export_findings_geojson,
    export_incidents_csv,
    export_incidents_geojson,
)
from disaster_monitor.application.interoperability.feeds import export_watch_atom
from disaster_monitor.application.interoperability.incident_brief import (
    DeterministicIncidentBriefBuilder,
)
from disaster_monitor.application.interoperability.ogc_features import (
    OgcFeatureProjection,
)
from disaster_monitor.presentation.http.incident_routes import (
    get_active_incidents_service,
    get_incident_watches,
)

router = APIRouter()


@router.get("/incidents.geojson", tags=["interoperability"])
async def incident_geojson(
    service: Annotated[ActiveIncidentsService, Depends(get_active_incidents_service)],
) -> dict[str, object]:
    return export_incidents_geojson(await service.execute())


@router.get("/incidents.csv", tags=["interoperability"])
async def incident_csv(
    service: Annotated[ActiveIncidentsService, Depends(get_active_incidents_service)],
) -> Response:
    return Response(
        export_incidents_csv(await service.execute()),
        media_type="text/csv; charset=utf-8",
    )


@router.get("/incidents/{event_id}/brief.html", tags=["interoperability"])
async def incident_brief(
    event_id: str,
    service: Annotated[ActiveIncidentsService, Depends(get_active_incidents_service)],
) -> Response:
    snapshot = await service.execute()
    incident = next(
        (item for item in snapshot.incidents if item.event_id == event_id), None
    )
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    coverage = next(
        item for item in snapshot.coverage if item.disaster is incident.disaster
    )
    brief = DeterministicIncidentBriefBuilder().build(
        incident,
        coverage=coverage,
        retrieved_at=snapshot.retrieved_at,
        gaps=snapshot.warnings,
    )
    return Response(brief.html, media_type="text/html; charset=utf-8")


@router.get("/ogc", tags=["interoperability"])
async def ogc_landing() -> dict[str, object]:
    return {
        "title": "DisasterMonitor OGC API Features projection",
        "links": [{"rel": "data", "href": "/api/v1/ogc/collections"}],
    }


@router.get("/ogc/collections", tags=["interoperability"])
async def ogc_collections() -> dict[str, object]:
    return {
        "collections": [
            {"id": value, "itemType": "feature"}
            for value in OgcFeatureProjection.collections
        ]
    }


@router.get("/ogc/collections/{collection}/items", tags=["interoperability"])
async def ogc_items(
    collection: str,
    service: Annotated[ActiveIncidentsService, Depends(get_active_incidents_service)],
    bbox: Annotated[str | None, Query()] = None,
    occurrence_start: Annotated[datetime | None, Query()] = None,
    occurrence_end: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> dict[str, object]:
    try:
        parsed_bbox = _bbox(bbox)
        return OgcFeatureProjection(await service.execute()).query(
            collection,
            bbox=parsed_bbox,
            occurrence_start=occurrence_start,
            occurrence_end=occurrence_end,
            limit=limit,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/incidents/{event_id}/provenance", tags=["interoperability"])
async def incident_provenance(
    event_id: str,
    service: Annotated[ActiveIncidentsService, Depends(get_active_incidents_service)],
) -> dict[str, object]:
    snapshot = await service.execute()
    incident = next(
        (item for item in snapshot.incidents if item.event_id == event_id), None
    )
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    return asdict(ProvenanceGraphBuilder().for_incident(incident))


@router.get("/incidents/{event_id}/why", tags=["interoperability"])
async def incident_why(
    event_id: str,
    service: Annotated[ActiveIncidentsService, Depends(get_active_incidents_service)],
) -> dict[str, object]:
    snapshot = await service.execute()
    incident = next(
        (item for item in snapshot.incidents if item.event_id == event_id), None
    )
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    graph = ProvenanceGraphBuilder().for_incident(incident)
    return asdict(ExplainEvidenceTrace().for_event(event_id, graph))


@router.get("/incident-watches/{watch_id}/feed.atom", tags=["interoperability"])
async def watch_atom(
    watch_id: str,
    request: Request,
    watches: Annotated[ManageIncidentWatches, Depends(get_incident_watches)],
) -> Response:
    try:
        changes = await watches.timeline(watch_id, limit=500)
    except IncidentWatchNotFoundError as error:
        raise HTTPException(
            status_code=404, detail="Incident watch not found."
        ) from error
    return Response(
        export_watch_atom(watch_id, changes, base_url=str(request.base_url)),
        media_type="application/atom+xml; charset=utf-8",
    )


@router.get("/incident-watches/{watch_id}/findings.{format}", tags=["interoperability"])
async def watch_findings(
    watch_id: str,
    format: str,
    watches: Annotated[ManageIncidentWatches, Depends(get_incident_watches)],
) -> Response:
    try:
        changes = await watches.timeline(watch_id, limit=500)
    except IncidentWatchNotFoundError as error:
        raise HTTPException(
            status_code=404, detail="Incident watch not found."
        ) from error
    if format == "csv":
        return Response(export_findings_csv(changes), media_type="text/csv")
    if format == "geojson":
        import json

        return Response(
            json.dumps(export_findings_geojson(changes), separators=(",", ":")),
            media_type="application/geo+json",
        )
    raise HTTPException(status_code=404, detail="Finding export format not found.")


def _bbox(value: str | None) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    parts = tuple(float(item) for item in value.split(","))
    if len(parts) != 4:
        raise ValueError("bbox requires west,south,east,north.")
    west, south, east, north = parts
    if not (-180 <= west <= east <= 180 and -90 <= south <= north <= 90):
        raise ValueError("bbox is outside ordered WGS84 bounds.")
    return west, south, east, north


__all__ = ["router"]
