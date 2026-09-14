"""Deterministic satellite-imagery catalog and protected-tile boundary tests."""

from __future__ import annotations

import httpx
import pytest

from disaster_monitor.application.ports.satellite_imagery import SatelliteTileRequest
from disaster_monitor.application.satellite_imagery import (
    SatelliteImageryInputError,
    SatelliteImageryService,
)
from disaster_monitor.infrastructure.composition import AppDependencyOverrides
from disaster_monitor.infrastructure.satellite_imagery.providers import (
    NasaGibsImageryProvider,
)
from disaster_monitor.main import create_app


def _service() -> SatelliteImageryService:
    return SatelliteImageryService((NasaGibsImageryProvider(),))


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
    ]
    assert [product.temporal_mode for product in products[:3]] == ["daily"] * 3
    assert [product.temporal_mode for product in products[3:6]] == ["subdaily"] * 3
    assert all(product.temporal_step_minutes == 10 for product in products[3:6])
    assert all(product.access_mode == "direct_gibs" for product in products)
    assert "planet" not in repr(products).casefold()
    assert "sentinel hub" not in repr(products).casefold()


async def test_http_catalog_exposes_only_public_nasa_gibs() -> None:
    app = create_app(
        overrides=AppDependencyOverrides(satellite_imagery_service=_service())
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/satellite-imagery")

    assert response.status_code == 200
    body = response.json()
    products = {item["source_id"]: item for item in body["products"]}
    assert products["nasa-viirs-snpp-true-color"]["available"] is True
    assert len(products) == 6
    assert "planet" not in response.text.casefold()
    assert "sentinel hub" not in response.text.casefold()
    assert "tile_url" not in response.text.casefold()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tile_request",
    (
        SatelliteTileRequest("planet", "planet-configured-mosaic", 1, 0, 0, None),
        SatelliteTileRequest("copernicus-data-space", "sentinel-2", 1, 0, 0, None),
    ),
)
async def test_invalid_provider_product_tile_and_date_inputs_are_rejected(
    tile_request: SatelliteTileRequest,
) -> None:
    service = _service()
    with pytest.raises(SatelliteImageryInputError):
        await service.fetch_tile(tile_request)
    await service.aclose()
