"""HTTP boundary for unverified field reports and contextual humanitarian data."""

from __future__ import annotations

import base64
import binascii
from dataclasses import asdict
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from disaster_monitor.application.field_reports.duplicates import (
    FieldReportDuplicateDetector,
)
from disaster_monitor.application.field_reports.importers import (
    ExternalFieldMapping,
    FieldReportImportService,
    UshahidiMapper,
)
from disaster_monitor.application.field_reports.service import (
    FieldReportConflictError,
    FieldReportEventNotFoundError,
    FieldReportNotFoundError,
    FieldReportService,
    IncidentEvidenceUnavailableError,
    NewFieldReport,
)
from disaster_monitor.application.humanitarian.context import (
    HumanitarianContextService,
)
from disaster_monitor.application.operator_workspace.service import (
    OperatorWorkspaceService,
)
from disaster_monitor.application.ports.operator_identity import (
    TrustedOperatorIdentityPolicy,
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
    FieldReviewCapabilityResponse,
)
from disaster_monitor.presentation.http.operator_identity import (
    get_trusted_operator_identity_policy,
    trusted_operator_id,
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
    response: Response,
    service: Annotated[FieldReportService, Depends(get_field_report_service)],
) -> dict[str, object]:
    try:
        prepared_media = tuple(
            service.sanitize_media(
                filename=item.filename,
                media_type=item.media_type,
                content=base64.b64decode(item.content_base64, validate=True),
            )
            for item in body.attachments
        )
        report, created = await service.submit_with_media(
            NewFieldReport(
                report_type=body.report_type,
                text=body.text,
                captured_at=body.captured_at,
                source_created_at=body.source_created_at,
                submitter_channel=body.submitter_channel,
                geometry=_geometry(body.geometry.type, body.geometry.coordinates),
                location_precision=body.location_precision,
                location_uncertainty_m=body.location_uncertainty_m,
            ),
            prepared_media,
        )
        if not created:
            response.status_code = status.HTTP_200_OK
        return asdict(report)
    except FieldReportConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
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


@router.get(
    "/field-reports/review-capability",
    response_model=FieldReviewCapabilityResponse,
    tags=["field-reports"],
)
async def field_review_capability(
    request: Request,
    policy: Annotated[
        TrustedOperatorIdentityPolicy,
        Depends(get_trusted_operator_identity_policy),
    ],
) -> FieldReviewCapabilityResponse:
    if not policy.enabled:
        return FieldReviewCapabilityResponse(available=False, reason="not_configured")
    identity = request.headers.get(policy.header_name, "").strip()
    if not identity or len(identity) > 200:
        return FieldReviewCapabilityResponse(available=False, reason="identity_missing")
    return FieldReviewCapabilityResponse(available=True, reason=None)


@router.post("/field-reports/{report_id}/reviews", tags=["field-reports"])
async def review_field_report(
    report_id: str,
    body: FieldReportReviewRequest,
    request: Request,
    policy: Annotated[
        TrustedOperatorIdentityPolicy,
        Depends(get_trusted_operator_identity_policy),
    ],
    service: Annotated[FieldReportService, Depends(get_field_report_service)],
) -> dict[str, object]:
    reviewer_id = trusted_operator_id(request, policy)
    try:
        return asdict(
            await service.review(
                report_id,
                body.decision,
                reviewer_id=reviewer_id,
                rationale=body.rationale,
                event_id=body.event_id,
                authority_policy_id=body.authority_policy_id,
            )
        )
    except FieldReportNotFoundError as error:
        raise HTTPException(
            status_code=404, detail="Field report not found."
        ) from error
    except FieldReportEventNotFoundError as error:
        raise HTTPException(status_code=404, detail="Incident not found.") from error
    except IncidentEvidenceUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post(
    "/field-reports/imports",
    tags=["field-reports"],
    status_code=status.HTTP_201_CREATED,
)
async def import_field_reports(
    body: FieldReportImportRequest,
    request: Request,
    policy: Annotated[
        TrustedOperatorIdentityPolicy,
        Depends(get_trusted_operator_identity_policy),
    ],
    service: Annotated[FieldReportService, Depends(get_field_report_service)],
) -> dict[str, object]:
    reviewer_id = trusted_operator_id(request, policy)
    importer = FieldReportImportService()
    try:
        media_by_external_id: dict[str, list[FieldMediaLineage]] = {}
        prepared_media = []
        for item in body.media_packages:
            target = media_by_external_id.setdefault(item.external_id, [])
            if len(target) >= 4:
                raise ValueError("Each imported record is limited to four media files.")
            prepared = service.sanitize_media(
                filename=item.filename,
                media_type=item.media_type,
                content=base64.b64decode(item.content_base64, validate=True),
            )
            target.append(prepared.lineage)
            prepared_media.append(prepared)
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
                body.content, reviewed_by=reviewer_id
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
                    reviewed_by=reviewer_id,
                    media_by_external_id=imported_media,
                )
            else:
                if not isinstance(body.content, dict):
                    raise ValueError("GeoJSON import content must be an object.")
                result = importer.import_geojson(
                    body.content,
                    source_system=body.source_system,
                    mapping=mapping,
                    reviewed_by=reviewer_id,
                    media_by_external_id=imported_media,
                )
        imported_record_ids = {
            report.import_provenance.source_record_id
            for report in result.reports
            if report.import_provenance is not None
        }
        if any(
            item.external_id not in imported_record_ids for item in body.media_packages
        ):
            raise ValueError(
                "An import media package did not match an imported record."
            )
        await service.import_reports(result.reports, tuple(prepared_media))
        return asdict(result)
    except (binascii.Error, ValueError) as error:
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
