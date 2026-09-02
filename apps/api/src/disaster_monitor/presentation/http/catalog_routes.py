"""FastAPI routes for the MVP."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from disaster_monitor.application.ports.event_media import MediaAssetStore
from disaster_monitor.application.ports.satellite_imagery import SatelliteTileRequest
from disaster_monitor.application.satellite_imagery import (
    SatelliteImageryInputError,
    SatelliteImageryService,
    SatelliteImageryUnavailableError,
    SatelliteImageryUpstreamError,
)
from disaster_monitor.application.source_catalog import SourceCatalogService
from disaster_monitor.application.weather_alerts import WeatherAlertsService
from disaster_monitor.presentation.http.schemas import (
    SatelliteImageryCatalogResponse,
    SatelliteImageryProductResponse,
    SourceCatalogItemResponse,
    SourceCatalogResponse,
    SourceOperationalStateResponse,
    WeatherAlertCoordinateResponse,
    WeatherAlertCoverageResponse,
    WeatherAlertGeometryResponse,
    WeatherAlertResponse,
    WeatherAlertsSnapshotResponse,
    WeatherAlertWarningResponse,
)

router = APIRouter()


def get_satellite_imagery_service(request: Request) -> SatelliteImageryService:
    """Retrieve the validated imagery use case built by the composition root."""
    return cast(
        SatelliteImageryService, request.app.state.dependencies.satellite_imagery
    )


def get_source_catalog_service(request: Request) -> SourceCatalogService:
    return cast(SourceCatalogService, request.app.state.dependencies.source_catalog)


def get_weather_alerts_service(request: Request) -> WeatherAlertsService:
    return cast(WeatherAlertsService, request.app.state.dependencies.weather_alerts)


def get_media_asset_store(request: Request) -> MediaAssetStore:
    return cast(MediaAssetStore, request.app.state.dependencies.media_assets)


@router.get(
    "/satellite-imagery",
    response_model=SatelliteImageryCatalogResponse,
    tags=["satellite-imagery"],
)
async def satellite_imagery_catalog(
    service: Annotated[SatelliteImageryService, Depends(get_satellite_imagery_service)],
) -> SatelliteImageryCatalogResponse:
    """Return product capabilities and configuration availability without secrets."""
    return SatelliteImageryCatalogResponse(
        products=[
            SatelliteImageryProductResponse(
                source_id=product.source_id,
                display_name=product.display_name,
                provider_id=product.provider_id,
                provider_name=product.provider_name,
                temporal_mode=product.temporal_mode,
                temporal_step_minutes=product.temporal_step_minutes,
                attribution=product.attribution,
                maximum_useful_zoom=product.maximum_useful_zoom,
                access_mode=product.access_mode,
                available=product.available,
            )
            for product in service.catalog()
        ]
    )


@router.get(
    "/sources",
    response_model=SourceCatalogResponse,
    tags=["sources"],
)
async def source_catalog(
    service: Annotated[SourceCatalogService, Depends(get_source_catalog_service)],
) -> SourceCatalogResponse:
    """Return maintained source metadata plus separately labelled runtime state."""
    snapshot = service.read()
    return SourceCatalogResponse(
        catalog_version=snapshot.catalog_version,
        sources=[
            SourceCatalogItemResponse(
                source_id=item.source_id,
                provider=item.provider,
                publisher=item.publisher,
                authority=item.authority,
                information_roles=list(item.information_roles),
                supported_disasters=list(item.supported_disasters),
                geographic_scopes=list(item.geographic_scopes),
                country_codes=(
                    list(item.country_codes) if item.country_codes is not None else None
                ),
                coverage_description=item.coverage_description,
                documentation_path=item.documentation_path,
                freshness_semantics=item.freshness_semantics,
                stale_threshold_seconds=item.stale_threshold_seconds,
                attribution=item.attribution,
                limitations=list(item.limitations),
                operational_state=SourceOperationalStateResponse(
                    registered=item.operational_state.registered,
                    configured=item.operational_state.configured,
                    availability=item.operational_state.availability,
                    availability_detail=item.operational_state.availability_detail,
                    provider_tier=item.operational_state.provider_tier,
                    execution_roles=list(item.operational_state.execution_roles),
                ),
            )
            for item in snapshot.sources
        ],
    )


@router.get(
    "/weather-alerts",
    response_model=WeatherAlertsSnapshotResponse,
    tags=["weather-alerts"],
)
async def weather_alerts(
    service: Annotated[WeatherAlertsService, Depends(get_weather_alerts_service)],
) -> WeatherAlertsSnapshotResponse:
    """Return bounded authoritative warnings without physical-event conversion."""
    snapshot = await service.execute()
    return WeatherAlertsSnapshotResponse(
        retrieved_at=snapshot.retrieved_at,
        alerts=[
            WeatherAlertResponse(
                provider_alert_id=alert.provider_alert_id,
                source_id=alert.source_id,
                publisher=alert.publisher,
                event=alert.event,
                headline=alert.headline,
                severity=alert.severity.value,
                urgency=alert.urgency.value,
                certainty=alert.certainty.value,
                sent=alert.sent,
                effective=alert.effective,
                onset=alert.onset,
                expires=alert.expires,
                affected_area=alert.affected_area,
                geometry=(
                    WeatherAlertGeometryResponse(
                        rings=[
                            [
                                WeatherAlertCoordinateResponse(
                                    latitude=coordinate.latitude,
                                    longitude=coordinate.longitude,
                                )
                                for coordinate in ring
                            ]
                            for ring in alert.geometry.rings
                        ]
                    )
                    if alert.geometry is not None
                    else None
                ),
                canonical_url=alert.canonical_url,
                retrieved_at=alert.retrieved_at,
                attribution=alert.attribution,
                limitations=list(alert.limitations),
            )
            for alert in snapshot.alerts
        ],
        coverage=WeatherAlertCoverageResponse(
            source_id=snapshot.coverage.source_id,
            publisher=snapshot.coverage.publisher,
            state=snapshot.coverage.state.value,
            detail=snapshot.coverage.detail,
            geographic_scope=snapshot.coverage.geographic_scope,
            limitations=list(snapshot.coverage.limitations),
        ),
        warnings=[
            WeatherAlertWarningResponse(
                reason_code=warning.reason_code,
                detail=warning.detail,
                retryable=warning.retryable,
                partial=warning.partial,
            )
            for warning in snapshot.warnings
        ],
    )


@router.get(
    "/satellite-imagery/tiles/{provider_id}/{source_id}/{z}/{x}/{y}",
    tags=["satellite-imagery"],
)
async def satellite_imagery_tile(
    provider_id: str,
    source_id: str,
    z: int,
    x: int,
    y: int,
    service: Annotated[SatelliteImageryService, Depends(get_satellite_imagery_service)],
    time: Annotated[str | None, Query(min_length=10, max_length=32)] = None,
) -> Response:
    """Fetch one validated protected tile from a fixed configured upstream."""
    try:
        tile = await service.fetch_tile(
            SatelliteTileRequest(provider_id, source_id, z, x, y, time)
        )
    except SatelliteImageryInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except SatelliteImageryUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except SatelliteImageryUpstreamError as error:
        status_code = 504 if error.reason_code == "timeout" else 502
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    return Response(
        content=tile.content,
        media_type=tile.media_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get(
    "/media/{media_id}",
    name="event_media_asset",
    status_code=status.HTTP_200_OK,
    tags=["assistant"],
)
async def event_media_asset(
    media_id: str,
    store: Annotated[MediaAssetStore, Depends(get_media_asset_store)],
) -> Response:
    """Serve only bounded image bytes already admitted by source-media policy."""
    asset = store.get(media_id)
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Media not found."
        )
    return Response(
        content=asset.content,
        media_type=asset.media_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )
