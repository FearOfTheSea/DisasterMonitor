"""Read collected reporting even when no interpreted event contains its capture."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from disaster_monitor.application.incidents.collected_reporting import (
    ReportingCatalogChanged,
    collected_reporting_page,
)
from disaster_monitor.application.incidents.discovery_scan import DiscoveryScanService
from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.presentation.http.common_response_serialization import (
    _source_response,
)
from disaster_monitor.presentation.http.discovery_routes import service
from disaster_monitor.presentation.http.event_schemas import (
    RetainedReportingPageResponse,
    SourceResponse,
)

router = APIRouter()


class CollectedReportResponse(BaseModel):
    capture_id: str
    source: SourceResponse
    bylines: list[str]
    origin: str | None = None
    original_url: str | None = None
    disaster: Disaster | None = None
    eligibility: Literal[
        "eligible",
        "unknown_publication",
        "outside_interval",
        "unclassified",
        "uncertain_publication",
    ]
    event_linked: bool
    access_issue: str | None = None
    text_preview: str


class CollectedReportingResponse(BaseModel):
    items: list[CollectedReportResponse]
    version: str
    offset: int = Field(ge=0)
    total: int = Field(ge=0)
    next_offset: int | None = Field(default=None, ge=0)
    unlinked_only: bool


@router.get(
    "/discovery-scans/{scan_id}/reporting",
    response_model=CollectedReportingResponse,
    tags=["discovery"],
)
async def collected_reports(
    scan_id: UUID,
    scans: Annotated[DiscoveryScanService, Depends(service)],
    offset: Annotated[int, Query(ge=0)] = 0,
    version: str | None = None,
    unlinked_only: bool = True,
) -> CollectedReportingResponse:
    try:
        page = collected_reporting_page(
            await scans.get(str(scan_id)),
            offset=offset,
            version=version,
            unlinked_only=unlinked_only,
        )
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ReportingCatalogChanged as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return CollectedReportingResponse(
        items=[
            CollectedReportResponse(
                capture_id=item.capture_id,
                source=_source_response(item.report.article.source),
                bylines=list(item.report.article.bylines),
                origin=item.report.article.origin,
                original_url=item.report.article.original_url,
                disaster=item.report.disaster,
                eligibility=item.report.eligibility,
                event_linked=item.event_linked,
                access_issue=item.report.article.access_issue,
                text_preview=item.report.article.text[:180],
            )
            for item in page.items
        ],
        version=page.version,
        offset=page.offset,
        total=page.total,
        next_offset=page.next_offset,
        unlinked_only=page.unlinked_only,
    )


@router.get(
    "/discovery-scans/{scan_id}/reporting/{capture_id}",
    response_model=RetainedReportingPageResponse,
    tags=["discovery"],
)
async def collected_report_text(
    scan_id: UUID,
    capture_id: str,
    scans: Annotated[DiscoveryScanService, Depends(service)],
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RetainedReportingPageResponse:
    try:
        page = await scans.reporting_text(str(scan_id), capture_id, offset=offset)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return RetainedReportingPageResponse(
        capture_id=page.capture_id,
        source=_source_response(page.article.source),
        bylines=list(page.article.bylines),
        origin=page.article.origin,
        original_url=page.article.original_url,
        text=page.text,
        offset=page.offset,
        total_characters=page.total_characters,
        next_offset=page.next_offset,
        unavailable_reason=page.unavailable_reason,
    )
