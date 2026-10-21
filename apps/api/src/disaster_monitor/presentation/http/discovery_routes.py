"""Start and inspect independently running publication-window scans."""

from datetime import datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from disaster_monitor.application.incidents.discovery_projection import (
    discovery_incident,
)
from disaster_monitor.application.incidents.discovery_scan import DiscoveryScanService
from disaster_monitor.application.ports.collection import ARTICLE_RETRIEVAL_PROVIDER
from disaster_monitor.application.ports.discovery import DiscoveryCapacityError
from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.discovery import (
    AcquisitionAudit,
    CollectionProgress,
    DiscoveryRun,
)
from disaster_monitor.presentation.http.active_incident_serialization import (
    active_incident_response,
)
from disaster_monitor.presentation.http.schemas import (
    ActiveIncidentsSnapshotResponse,
    DisasterIncidentCoverageResponse,
)

router = APIRouter()


class DiscoveryScanRequest(BaseModel):
    reporting_days: Literal[1, 3, 7, 14, 30] = 7


class DiscoveryScanResponse(BaseModel):
    scan_id: str
    reprocessed_from: str | None = None
    collection: CollectionProgress | None = None
    reporting_days: int
    interval_start: datetime
    interval_end: datetime
    status: Literal["running", "completed", "incomplete", "failed"]
    finished_at: datetime | None
    issues: list[str]
    truncated: bool
    reports_seen: int
    unknown_publication_count: int
    unlocated_count: int
    candidate_count: int = 0
    associated_event_count: int = 0
    uncertain_publication_count: int = 0
    successful_operations: int
    failed_operations: int
    acquisition: list[AcquisitionAudit] = Field(default_factory=list)
    assessment_counts: dict[str, int] = Field(default_factory=dict)
    snapshot: ActiveIncidentsSnapshotResponse
    coverage_notice: str = Field(
        default="Completion describes this scan process. Worldwide coverage is not "
        "exhaustive; provider indexing, language, article access, "
        "and extraction limits remain."
    )


def service(request: Request) -> DiscoveryScanService:
    value = request.app.state.dependencies.discovery_scans
    if value is None:
        raise HTTPException(503, "Discovery scans are unavailable.")
    return cast(DiscoveryScanService, value)


def scan_response(run: DiscoveryRun) -> DiscoveryScanResponse:
    retrieved_at = run.finished_at or max(
        (report.article.source.retrieved_at for report in run.reports),
        default=run.interval.end,
    )
    incidents = tuple(
        discovery_incident(event, retrieved_at, scan_id=run.scan_id)
        for event in run.events
    )
    return DiscoveryScanResponse(
        scan_id=run.scan_id,
        reprocessed_from=run.reprocessed_from,
        collection=run.collection,
        reporting_days=run.interval.days,
        interval_start=run.interval.start,
        interval_end=run.interval.end,
        status=run.status,
        finished_at=run.finished_at,
        issues=list(run.issues),
        truncated=run.truncated,
        reports_seen=len(run.reports),
        candidate_count=sum(e.identity_status == "candidate" for e in run.events),
        associated_event_count=sum(
            e.identity_status == "associated" for e in run.events
        ),
        uncertain_publication_count=sum(
            r.eligibility == "uncertain_publication" for r in run.reports
        ),
        unknown_publication_count=sum(
            r.eligibility == "unknown_publication" for r in run.reports
        ),
        unlocated_count=sum(item.geometry is None for item in incidents),
        successful_operations=run.successful_operations,
        failed_operations=run.failed_operations,
        acquisition=list(run.acquisition),
        assessment_counts={
            **{
                status: sum(report.eligibility == status for report in run.reports)
                for status in (
                    "eligible",
                    "unknown_publication",
                    "outside_interval",
                    "unclassified",
                    "uncertain_publication",
                )
            },
            "empty_extracted_text": sum(
                not report.article.text for report in run.reports
            ),
            "reports_with_fatality_evidence": sum(
                bool(report.fatality_evidence) for report in run.reports
            ),
            "associated_events": sum(
                e.identity_status == "associated" for e in run.events
            ),
            "event_candidates": sum(
                e.identity_status == "candidate" for e in run.events
            ),
            "extracted_mentions": sum(len(r.mentions) for r in run.reports),
            "events_with_geometry": sum(
                event.geometry is not None for event in run.events
            ),
            "events_with_onset": sum(
                event.event_time is not None for event in run.events
            ),
        },
        snapshot=ActiveIncidentsSnapshotResponse(
            retrieved_at=retrieved_at,
            incidents=[active_incident_response(item) for item in incidents],
            coverage=[
                DisasterIncidentCoverageResponse(
                    disaster=disaster,
                    state="degraded"
                    if run.status in ("running", "incomplete")
                    else "unavailable"
                    if run.status == "failed"
                    else "events_found"
                    if any(i.disaster == disaster for i in incidents)
                    else "no_matching_records",
                    incident_count=sum(i.disaster == disaster for i in incidents),
                    providers=_checked_providers(run),
                    detail="Publication-window scan; reporting remains "
                    "attributed and unverified.",
                    scan_complete=run.status == "completed",
                    truncated=run.truncated,
                    records_seen=sum(r.disaster == disaster for r in run.reports),
                )
                for disaster in Disaster
            ],
            warnings=list(run.issues),
            total_incident_count=len(incidents),
            snapshot_version=run.scan_id,
        ),
    )


def _checked_providers(run: DiscoveryRun) -> list[str]:
    if run.collection is not None:
        return sorted(
            {
                provider
                for provider, requests in run.collection.provider_requests
                if requests > 0 and provider != ARTICLE_RETRIEVAL_PROVIDER
            }
        )
    return ["open-news"] if run.successful_operations or run.failed_operations else []


@router.post(
    "/discovery-scans",
    response_model=DiscoveryScanResponse,
    status_code=202,
    tags=["discovery"],
)
async def start_scan(
    body: DiscoveryScanRequest, scans: Annotated[DiscoveryScanService, Depends(service)]
) -> DiscoveryScanResponse:
    try:
        return scan_response(await scans.start(body.reporting_days))
    except DiscoveryCapacityError as error:
        raise HTTPException(507, str(error)) from error
    except ValueError as error:
        raise HTTPException(429, str(error)) from error


@router.get(
    "/discovery-scans/{scan_id}",
    response_model=DiscoveryScanResponse,
    tags=["discovery"],
)
async def get_scan(
    scan_id: UUID, scans: Annotated[DiscoveryScanService, Depends(service)]
) -> DiscoveryScanResponse:
    try:
        return scan_response(await scans.get(str(scan_id)))
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@router.post(
    "/discovery-scans/{scan_id}/reprocess",
    response_model=DiscoveryScanResponse,
    status_code=202,
    tags=["discovery"],
)
async def reprocess_scan(
    scan_id: UUID, scans: Annotated[DiscoveryScanService, Depends(service)]
) -> DiscoveryScanResponse:
    try:
        return scan_response(await scans.reprocess(str(scan_id)))
    except DiscoveryCapacityError as error:
        raise HTTPException(507, str(error)) from error
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@router.post(
    "/discovery-scans/{scan_id}/continue",
    response_model=DiscoveryScanResponse,
    status_code=202,
    tags=["discovery"],
)
async def continue_scan(
    scan_id: UUID, scans: Annotated[DiscoveryScanService, Depends(service)]
) -> DiscoveryScanResponse:
    try:
        return scan_response(await scans.continue_collection(str(scan_id)))
    except DiscoveryCapacityError as error:
        raise HTTPException(507, str(error)) from error
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
