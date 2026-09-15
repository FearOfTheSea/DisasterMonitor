"""HTTP boundary for unverified field reports and contextual humanitarian data."""

from __future__ import annotations

import base64
import binascii
from dataclasses import asdict
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from disaster_monitor.application.field_reports.duplicates import (
    FieldReportDuplicateDetector,
)
from disaster_monitor.application.field_reports.importers import (
    ExternalFieldMapping,
    FieldReportImportService,
    UshahidiMapper,
)
from disaster_monitor.application.field_reports.service import (
    FieldReportNotFoundError,
    FieldReportService,
    NewFieldReport,
)
from disaster_monitor.application.humanitarian.context import (
    HumanitarianContextService,
)
from disaster_monitor.application.operator_workspace.service import (
    OperatorWorkspaceService,
)
from disaster_monitor.domain.field_reports import (
    FieldCoordinate,
    FieldMediaLineage,
    FieldReportGeometry,
    FieldReportGeometryKind,
    FieldReportReviewState,
)
from disaster_monitor.presentation.http.field_report_schemas import (
    FieldReportCreateRequest,
    FieldReportImportRequest,
    FieldReportReviewRequest,
)

router = APIRouter()


def get_field_report_service(request: Request) -> FieldReportService:
    return cast(FieldReportService, request.app.state.dependencies.field_reports)


def get_operator_workspace_service(request: Request) -> OperatorWorkspaceService:
    return cast(
        OperatorWorkspaceService, request.app.state.dependencies.operator_workspace
    )


def get_humanitarian_context_service(request: Request) -> HumanitarianContextService:
    return cast(
        HumanitarianContextService,
        request.app.state.dependencies.humanitarian_context,
    )


@router.post(
    "/field-reports",
    tags=["field-reports"],
    status_code=status.HTTP_201_CREATED,
)
async def submit_field_report(
    body: FieldReportCreateRequest,
    service: Annotated[FieldReportService, Depends(get_field_report_service)],
) -> dict[str, object]:
    try:
        media = tuple(
            service.admit_media(
                filename=item.filename,
                media_type=item.media_type,
                content=base64.b64decode(item.content_base64, validate=True),
            )
            for item in body.attachments
        )
        report = await service.submit(
            NewFieldReport(
                report_type=body.report_type,
                text=body.text,
                captured_at=body.captured_at,
                source_created_at=body.source_created_at,
                submitter_channel=body.submitter_channel,
                geometry=_geometry(body.geometry.type, body.geometry.coordinates),
                location_precision=body.location_precision,
                location_uncertainty_m=body.location_uncertainty_m,
                media=media,
            )
        )
        return asdict(report)
    except (binascii.Error, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/field-reports", tags=["field-reports"])
async def list_field_reports(
    service: Annotated[FieldReportService, Depends(get_field_report_service)],
    review_state: Annotated[FieldReportReviewState | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, object]]:
    reports = await service.list_queue(review_state=review_state, limit=limit)
    return [asdict(report) for report in reports]


@router.get("/field-reports/duplicate-candidates", tags=["field-reports"])
async def field_report_duplicate_candidates(
    service: Annotated[FieldReportService, Depends(get_field_report_service)],
) -> list[dict[str, object]]:
    reports = await service.list_queue(limit=500)
    return [asdict(item) for item in FieldReportDuplicateDetector().detect(reports)]


@router.post("/field-reports/{report_id}/reviews", tags=["field-reports"])
async def review_field_report(
    report_id: str,
    body: FieldReportReviewRequest,
    service: Annotated[FieldReportService, Depends(get_field_report_service)],
) -> dict[str, object]:
    try:
        return asdict(
            await service.review(
                report_id,
                body.decision,
                reviewer_id=body.reviewer_id,
                rationale=body.rationale,
                event_id=body.event_id,
                authority_policy_id=body.authority_policy_id,
            )
        )
    except FieldReportNotFoundError as error:
        raise HTTPException(
            status_code=404, detail="Field report not found."
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post(
    "/field-reports/imports",
    tags=["field-reports"],
    status_code=status.HTTP_201_CREATED,
)
async def import_field_reports(
    body: FieldReportImportRequest,
    service: Annotated[FieldReportService, Depends(get_field_report_service)],
) -> dict[str, object]:
    importer = FieldReportImportService()
    try:
        media_by_external_id: dict[str, list[FieldMediaLineage]] = {}
        for item in body.media_packages:
            target = media_by_external_id.setdefault(item.external_id, [])
            if len(target) >= 4:
                raise ValueError("Each imported record is limited to four media files.")
            target.append(
                service.admit_media(
                    filename=item.filename,
                    media_type=item.media_type,
                    content=base64.b64decode(item.content_base64, validate=True),
                )
            )
        imported_media = {
            external_id: tuple(items)
            for external_id, items in media_by_external_id.items()
        }
        if body.format == "ushahidi":
            if not isinstance(body.content, dict):
                raise ValueError("Ushahidi import content must be a JSON object.")
            if body.media_packages:
                raise ValueError(
                    "Ushahidi media packages are not supported by this mapping."
                )
            result = UshahidiMapper().import_posts(
                body.content, reviewed_by=body.reviewed_by
            )
        else:
            if body.mapping is None:
                raise ValueError("CSV and GeoJSON imports require explicit mapping.")
            mapping = ExternalFieldMapping(**body.mapping.model_dump())
            if body.format == "csv":
                if not isinstance(body.content, str):
                    raise ValueError("CSV import content must be text.")
                result = importer.import_csv(
                    body.content,
                    source_system=body.source_system,
                    mapping=mapping,
                    reviewed_by=body.reviewed_by,
                    media_by_external_id=imported_media,
                )
            else:
                if not isinstance(body.content, dict):
                    raise ValueError("GeoJSON import content must be an object.")
                result = importer.import_geojson(
                    body.content,
                    source_system=body.source_system,
                    mapping=mapping,
                    reviewed_by=body.reviewed_by,
                    media_by_external_id=imported_media,
                )
        await service.import_reports(result.reports)
        return asdict(result)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/field-reports/ushahidi-export", tags=["field-reports"])
async def export_field_reports_for_ushahidi(
    service: Annotated[FieldReportService, Depends(get_field_report_service)],
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
) -> dict[str, object]:
    reports = await service.list_queue(limit=limit)
    return UshahidiMapper().export_posts(reports)


@router.get("/humanitarian-context/{country_code}", tags=["humanitarian-context"])
async def humanitarian_context(
    country_code: str,
    service: Annotated[
        HumanitarianContextService, Depends(get_humanitarian_context_service)
    ],
    event_id: Annotated[str | None, Query()] = None,
) -> dict[str, object]:
    try:
        return asdict(await service.for_country(country_code, event_id=event_id))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _geometry(kind: str, raw_coordinates: list[object]) -> FieldReportGeometry:
    if kind == "Point":
        if len(raw_coordinates) < 2:
            raise ValueError("Point geometry requires longitude and latitude.")
        return FieldReportGeometry(
            FieldReportGeometryKind.POINT,
            (
                FieldCoordinate(
                    longitude=float(str(raw_coordinates[0])),
                    latitude=float(str(raw_coordinates[1])),
                ),
            ),
        )
    if not raw_coordinates or not isinstance(raw_coordinates[0], list):
        raise ValueError("Polygon geometry requires one exterior ring.")
    return FieldReportGeometry(
        FieldReportGeometryKind.POLYGON,
        tuple(
            FieldCoordinate(longitude=float(item[0]), latitude=float(item[1]))
            for item in raw_coordinates[0]
            if isinstance(item, list) and len(item) >= 2
        ),
    )


__all__ = [
    "get_field_report_service",
    "get_humanitarian_context_service",
    "get_operator_workspace_service",
    "router",
]
