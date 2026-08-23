"""Deterministic satellite-imagery catalog and protected-tile boundary tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import httpx
import pytest

from disaster_monitor.application.ports.satellite_imagery import SatelliteTileRequest
from disaster_monitor.application.satellite_imagery import (
    SatelliteImageryInputError,
    SatelliteImageryService,
    SatelliteImageryUnavailableError,
    SatelliteImageryUpstreamError,
)
from disaster_monitor.infrastructure.satellite_imagery.providers import (
    NasaGibsImageryProvider,
    PlanetImageryProvider,
    SentinelHubImageryProvider,
)
from disaster_monitor.main import create_app

PNG = b"\x89PNG\r\n\x1a\nfixture"


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=2)


def _service(
    *,
    sentinel_client: httpx.AsyncClient | None = None,
    planet_client: httpx.AsyncClient | None = None,
    sentinel_instance_id: str | None = "server-secret-instance",
    planet_api_key: str | None = "server-secret-key",
    planet_mosaic_name: str | None = "server-private-mosaic-2026",
    maximum_response_bytes: int = 1_000_000,
) -> SatelliteImageryService:
    return SatelliteImageryService(
        (
            NasaGibsImageryProvider(),
            SentinelHubImageryProvider(
                instance_id=sentinel_instance_id,
                layer_id="TRUE_COLOR",
                client=sentinel_client,
                timeout_seconds=2,
                maximum_response_bytes=maximum_response_bytes,
            ),
            PlanetImageryProvider(
                api_key=planet_api_key,
                mosaic_name=planet_mosaic_name,
                client=planet_client,
                timeout_seconds=2,
                maximum_response_bytes=maximum_response_bytes,
            ),
        )
    )


def test_catalog_has_exact_source_capabilities_without_credentials() -> None:
    service = _service()

    products = service.catalog()

    assert [product.source_id for product in products] == [
        "nasa-viirs-snpp-true-color",
        "nasa-modis-terra-true-color",
        "nasa-modis-aqua-true-color",
        "nasa-goes-east-geocolor",
        "nasa-goes-west-geocolor",
        "nasa-himawari-9-visible",
        "copernicus-sentinel-2-true-color",
        "planet-configured-mosaic",
    ]
    assert [product.temporal_mode for product in products[:3]] == ["daily"] * 3
    assert [product.temporal_mode for product in products[3:6]] == ["subdaily"] * 3
    assert all(product.temporal_step_minutes == 10 for product in products[3:6])
    assert products[-2].temporal_mode == "daily"
    assert products[-1].temporal_mode == "fixed"
    serialized = repr(products)
    assert "server-secret-instance" not in serialized
    assert "server-secret-key" not in serialized
    assert "server-private-mosaic-2026" not in serialized


@pytest.mark.asyncio
async def test_http_catalog_disables_unconfigured_credentialed_providers() -> None:
    app = create_app(
        satellite_imagery_service=_service(
            sentinel_instance_id=None,
            planet_api_key=None,
            planet_mosaic_name=None,
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/satellite-imagery")

    assert response.status_code == 200
    body = response.json()
    products = {item["source_id"]: item for item in body["products"]}
    assert products["nasa-viirs-snpp-true-color"]["available"] is True
    assert products["copernicus-sentinel-2-true-color"]["available"] is False
    assert products["planet-configured-mosaic"]["available"] is False
    assert "secret" not in response.text.casefold()
    assert "instance" not in response.text.casefold()
    assert "api_key" not in response.text.casefold()
    assert "tile_url" not in response.text.casefold()


@pytest.mark.asyncio
async def test_sentinel_proxy_constructs_bounded_web_mercator_wms_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    client = _client(handler)
    service = _service(sentinel_client=client)
    try:
        tile = await service.fetch_tile(
            SatelliteTileRequest(
                provider_id="copernicus-sentinel-hub",
                source_id="copernicus-sentinel-2-true-color",
                z=1,
                x=1,
                y=0,
                observation_time="2026-08-20",
            )
        )
    finally:
        await service.aclose()

    assert tile.content == PNG
    assert tile.media_type == "image/png"
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == "services.sentinel-hub.com"
    assert request.url.path == "/ogc/wms/server-secret-instance"
    parameters = dict(request.url.params)
    assert parameters == {
        "BBOX": "0.000000,0.000000,20037508.342789,20037508.342789",
        "CRS": "EPSG:3857",
        "FORMAT": "image/png",
        "HEIGHT": "256",
        "LAYERS": "TRUE_COLOR",
        "REQUEST": "GetMap",
        "SERVICE": "WMS",
        "STYLES": "",
        "TIME": "2026-08-20T00:00:00Z/2026-08-20T23:59:59Z",
        "TRANSPARENT": "TRUE",
        "VERSION": "1.3.0",
        "WIDTH": "256",
    }


@pytest.mark.asyncio
async def test_planet_proxy_constructs_configured_mosaic_xyz_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    client = _client(handler)
    service = _service(planet_client=client)
    try:
        tile = await service.fetch_tile(
            SatelliteTileRequest(
                provider_id="planet",
                source_id="planet-configured-mosaic",
                z=4,
                x=9,
                y=6,
                observation_time=None,
            )
        )
    finally:
        await service.aclose()

    assert tile.content == PNG
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == "tiles.planet.com"
    assert request.url.path == (
        "/basemaps/v1/planet-tiles/server-private-mosaic-2026/gmap/4/9/6.png"
    )
    assert dict(request.url.params) == {"api_key": "server-secret-key"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tile_request",
    (
        SatelliteTileRequest("unknown", "planet-configured-mosaic", 1, 0, 0, None),
        SatelliteTileRequest("planet", "unknown", 1, 0, 0, None),
        SatelliteTileRequest(
            "copernicus-sentinel-hub",
            "copernicus-sentinel-2-true-color",
            -1,
            0,
            0,
            "2026-08-20",
        ),
        SatelliteTileRequest(
            "copernicus-sentinel-hub",
            "copernicus-sentinel-2-true-color",
            2,
            4,
            0,
            "2026-08-20",
        ),
        SatelliteTileRequest(
            "copernicus-sentinel-hub",
            "copernicus-sentinel-2-true-color",
            2,
            0,
            4,
            "2026-08-20",
        ),
        SatelliteTileRequest(
            "copernicus-sentinel-hub",
            "copernicus-sentinel-2-true-color",
            2,
            0,
            0,
            "2026-02-30",
        ),
        SatelliteTileRequest(
            "planet", "planet-configured-mosaic", 2, 0, 0, "2026-08-20"
        ),
    ),
)
async def test_invalid_provider_product_tile_and_date_inputs_are_rejected(
    tile_request: SatelliteTileRequest,
) -> None:
    service = _service()
    with pytest.raises(SatelliteImageryInputError):
        await service.fetch_tile(tile_request)
    await service.aclose()


@pytest.mark.asyncio
async def test_unconfigured_protected_provider_is_unavailable_without_network() -> None:
    service = _service(sentinel_instance_id=None)
    with pytest.raises(SatelliteImageryUnavailableError):
        await service.fetch_tile(
            SatelliteTileRequest(
                "copernicus-sentinel-hub",
                "copernicus-sentinel-2-true-color",
                2,
                1,
                1,
                date(2026, 8, 20).isoformat(),
            )
        )
    await service.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "maximum_response_bytes", "reason_code"),
    (
        (
            lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("slow")),
            1_000_000,
            "timeout",
        ),
        (
            lambda request: httpx.Response(
                502, content=b"bad gateway", headers={"content-type": "text/plain"}
            ),
            1_000_000,
            "http_error",
        ),
        (
            lambda request: httpx.Response(
                200, content=b"not an image", headers={"content-type": "text/plain"}
            ),
            1_000_000,
            "unexpected_content_type",
        ),
        (
            lambda request: httpx.Response(
                200,
                content=PNG,
                headers={"content-type": "image/svg+xml"},
            ),
            1_000_000,
            "unexpected_content_type",
        ),
        (
            lambda request: httpx.Response(
                200,
                content=PNG * 4,
                headers={"content-type": "image/png"},
            ),
            16,
            "response_too_large",
        ),
    ),
)
async def test_upstream_timeout_error_non_image_and_oversize_are_bounded(
    handler: Callable[[httpx.Request], httpx.Response],
    maximum_response_bytes: int,
    reason_code: str,
) -> None:
    client = _client(handler)
    service = _service(
        sentinel_client=client,
        maximum_response_bytes=maximum_response_bytes,
    )
    with pytest.raises(SatelliteImageryUpstreamError) as caught:
        await service.fetch_tile(
            SatelliteTileRequest(
                "copernicus-sentinel-hub",
                "copernicus-sentinel-2-true-color",
                2,
                1,
                1,
                "2026-08-20",
            )
        )
    assert caught.value.reason_code == reason_code
    await service.aclose()


@pytest.mark.asyncio
async def test_protected_tile_http_response_never_returns_credentials_or_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    service = _service(sentinel_client=_client(handler))
    app = create_app(satellite_imagery_service=service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/satellite-imagery/tiles/copernicus-sentinel-hub/"
            "copernicus-sentinel-2-true-color/2/1/1",
            params={"time": "2026-08-20"},
        )

    assert response.status_code == 200
    assert response.content == PNG
    assert response.headers["content-type"] == "image/png"
    assert "server-secret-instance" not in response.text
    assert "services.sentinel-hub.com" not in response.text
    await service.aclose()
