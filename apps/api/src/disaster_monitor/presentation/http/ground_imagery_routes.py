"""HTTP transport for the event-focused Ground view workflow."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from starlette.responses import Response

from disaster_monitor.application.ground_imagery.errors import (
    GroundImageryArtifactNotFound,
    GroundImageryError,
    GroundImageryIncidentNotFound,
    GroundImageryRequestNotFound,
)
from disaster_monitor.application.ground_imagery.models import (
    GroundImageryRequest,
    GroundImageryRequestInput,
)
from disaster_monitor.application.ground_imagery.service import (
    GroundImageryService,
)
from disaster_monitor.domain.imagery.observations import ImpactOnset, Sensor
from disaster_monitor.domain.imagery.regions import MultiPolygon, polygon_from_geojson
from disaster_monitor.presentation.http.ground_imagery_schemas import (
    GroundImageryCreateRequest,
    GroundImageryManifestResponse,
    GroundImageryObservationPageResponse,
    GroundImageryPrepareRequest,
    GroundImageryReadinessResponse,
    GroundImageryRegionRequest,
    GroundImageryRequestResponse,
    GroundImagerySelectionRequest,
    GroundImageryWatchRequest,
)
from disaster_monitor.presentation.http.ground_imagery_serialization import (
    ground_imagery_request_response,
    observation_page_response,
)

router = APIRouter(prefix="/ground-imagery", tags=["ground-imagery"])


def get_ground_imagery_service(request: Request) -> GroundImageryService:
    return cast(GroundImageryService, request.app.state.dependencies.ground_imagery)


@router.post(
    "/requests",
    response_model=GroundImageryRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_ground_imagery_request(
    payload: GroundImageryCreateRequest,
    service: Annotated[GroundImageryService, Depends(get_ground_imagery_service)],
) -> GroundImageryRequestResponse:
    try:
        request = await service.create_request(
            GroundImageryRequestInput(
                incident_id=payload.incident_id,
                reference_time=payload.reference_time or datetime.now(UTC),
                sensors=tuple(dict.fromkeys(payload.sensors)),
                user_region=_region_from_json(payload.region),
                context_margin_km=payload.context_margin_km,
                fallback_radius_km=payload.fallback_radius_km,
                owner_scope=payload.owner_scope,
                idempotency_key=payload.idempotency_key,
                onset_override=_onset_override(payload),
            )
        )
    except GroundImageryIncidentNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except GroundImageryError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return ground_imagery_request_response(request)


@router.get(
    "/readiness",
    response_model=GroundImageryReadinessResponse,
)
async def ground_imagery_readiness(
    service: Annotated[GroundImageryService, Depends(get_ground_imagery_service)],
) -> GroundImageryReadinessResponse:
    return GroundImageryReadinessResponse.model_validate(service.readiness())


@router.get(
    "/requests/{request_id}",
    response_model=GroundImageryRequestResponse,
)
async def get_ground_imagery_request(
    request_id: str,
    service: Annotated[GroundImageryService, Depends(get_ground_imagery_service)],
) -> GroundImageryRequestResponse:
    return ground_imagery_request_response(await _get(service, request_id))


@router.get(
    "/requests/{request_id}/observations",
    response_model=GroundImageryObservationPageResponse,
)
async def list_ground_imagery_observations(
    request_id: str,
    service: Annotated[GroundImageryService, Depends(get_ground_imagery_service)],
    sensor: Sensor | None = None,
    cursor: Annotated[int, Query(ge=0, le=500)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> GroundImageryObservationPageResponse:
    try:
        page = await service.observations(
            request_id,
            sensor=sensor,
            cursor=cursor,
            limit=limit,
        )
    except (GroundImageryRequestNotFound, ValueError) as error:
        raise HTTPException(
            status_code=404 if isinstance(error, GroundImageryRequestNotFound) else 422,
            detail=str(error),
        ) from error
    return observation_page_response(page.observations, page.next_cursor, page.total)


@router.post(
    "/requests/{request_id}/regions",
    response_model=GroundImageryRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def replace_ground_imagery_region(
    request_id: str,
    payload: GroundImageryRegionRequest,
    service: Annotated[GroundImageryService, Depends(get_ground_imagery_service)],
) -> GroundImageryRequestResponse:
    try:
        region = _region_from_json(payload.region)
        if region is None:
            raise ValueError("A replacement imagery region is required.")
        request = await service.replace_region(
            request_id,
            region,
            context_margin_km=payload.context_margin_km,
        )
    except GroundImageryRequestNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except GroundImageryError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return ground_imagery_request_response(request)


@router.post(
    "/requests/{request_id}/selections",
    response_model=GroundImageryRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def select_ground_imagery_observation(
    request_id: str,
    payload: GroundImagerySelectionRequest,
    service: Annotated[GroundImageryService, Depends(get_ground_imagery_service)],
) -> GroundImageryRequestResponse:
    try:
        request = await service.select_observation(
            request_id,
            sensor=payload.sensor,
            role=payload.role,
            observation_id=payload.observation_id,
        )
    except GroundImageryRequestNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except GroundImageryError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return ground_imagery_request_response(request)


@router.post(
    "/requests/{request_id}/prepare",
    response_model=GroundImageryRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def prepare_ground_imagery_selection(
    request_id: str,
    payload: GroundImageryPrepareRequest,
    service: Annotated[GroundImageryService, Depends(get_ground_imagery_service)],
) -> GroundImageryRequestResponse:
    try:
        request = await service.prepare_selection(
            request_id,
            sensor=payload.sensor,
            role=payload.role,
            overview=payload.overview,
            output_kind=payload.output_kind,
        )
    except GroundImageryRequestNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except GroundImageryError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return ground_imagery_request_response(request)


@router.post(
    "/requests/{request_id}/refresh",
    response_model=GroundImageryRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def refresh_ground_imagery_request(
    request_id: str,
    service: Annotated[GroundImageryService, Depends(get_ground_imagery_service)],
) -> GroundImageryRequestResponse:
    try:
        request = await service.refresh(request_id)
    except GroundImageryRequestNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except GroundImageryError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return ground_imagery_request_response(request)


@router.post(
    "/requests/{request_id}/cancel",
    response_model=GroundImageryRequestResponse,
)
async def cancel_ground_imagery_request(
    request_id: str,
    service: Annotated[GroundImageryService, Depends(get_ground_imagery_service)],
) -> GroundImageryRequestResponse:
    try:
        request = await service.cancel(request_id)
    except GroundImageryRequestNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return ground_imagery_request_response(request)


@router.put(
    "/requests/{request_id}/watch",
    response_model=GroundImageryRequestResponse,
)
async def set_ground_imagery_watch(
    request_id: str,
    payload: GroundImageryWatchRequest,
    service: Annotated[GroundImageryService, Depends(get_ground_imagery_service)],
) -> GroundImageryRequestResponse:
    try:
        request = await service.set_watch(
            request_id,
            enabled=payload.enabled,
            interval_seconds=payload.interval_seconds,
        )
    except GroundImageryRequestNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return ground_imagery_request_response(request)


@router.get(
    "/requests/{request_id}/manifest",
    response_model=GroundImageryManifestResponse,
)
async def ground_imagery_manifest(
    request_id: str,
    service: Annotated[GroundImageryService, Depends(get_ground_imagery_service)],
) -> GroundImageryManifestResponse:
    try:
        return GroundImageryManifestResponse.model_validate(
            await service.manifest(request_id)
        )
    except GroundImageryRequestNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get(
    "/selections/{selection_id_value}/manifest",
    response_model=GroundImageryManifestResponse,
)
async def ground_imagery_selection_manifest(
    selection_id_value: str,
    service: Annotated[GroundImageryService, Depends(get_ground_imagery_service)],
) -> GroundImageryManifestResponse:
    try:
        return GroundImageryManifestResponse.model_validate(
            await service.manifest_for_selection(selection_id_value)
        )
    except GroundImageryRequestNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/artifacts/{artifact_id}/download")
async def download_ground_imagery_artifact(
    artifact_id: str,
    service: Annotated[GroundImageryService, Depends(get_ground_imagery_service)],
) -> Response:
    try:
        stored = await service.read_artifact(artifact_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except GroundImageryError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    if stored is None:
        raise HTTPException(
            status_code=404, detail="The imagery artifact was not found."
        )
    metadata, content = stored
    return Response(
        content=content,
        media_type=metadata.content_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{metadata.artifact_id}.tif"'
            ),
            "ETag": metadata.etag,
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.get("/artifacts/{artifact_id}/tiles/{zoom}/{x}/{y}.png")
async def ground_imagery_tile(
    artifact_id: str,
    zoom: int,
    x: int,
    y: int,
    service: Annotated[GroundImageryService, Depends(get_ground_imagery_service)],
) -> Response:
    try:
        content = await service.render_tile(artifact_id, zoom, x, y)
    except GroundImageryArtifactNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except GroundImageryError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return Response(
        content=content,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )


async def _get(service: GroundImageryService, request_id: str) -> GroundImageryRequest:
    try:
        return await service.get_request(request_id)
    except GroundImageryRequestNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


def _region_from_json(value: dict[str, Any] | None) -> MultiPolygon | None:
    if value is None:
        return None
    if len(json.dumps(value, separators=(",", ":"))) > 2 * 1024 * 1024:
        raise ValueError("The imagery region GeoJSON exceeds the 2 MB limit.")
    geometry = polygon_from_geojson(value)
    if geometry.positions > 100_000:
        raise ValueError("The imagery region exceeds the 100,000-position limit.")
    return geometry


def _onset_override(payload: GroundImageryCreateRequest) -> ImpactOnset | None:
    values = (payload.onset_earliest, payload.onset_latest, payload.onset_source_id)
    if all(value is None for value in values):
        return None
    if (
        payload.onset_earliest is None
        or payload.onset_latest is None
        or payload.onset_source_id is None
    ):
        raise ValueError("An onset override requires earliest, latest, and source ID.")
    if payload.onset_earliest == payload.onset_latest:
        return ImpactOnset.exact(
            payload.onset_earliest,
            source_id=payload.onset_source_id,
        )
    return ImpactOnset.interval(
        payload.onset_earliest,
        payload.onset_latest,
        source_id=payload.onset_source_id,
    )
